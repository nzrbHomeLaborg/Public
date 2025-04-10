class ChangeDetector(Action):
    """
    Detect changed applications (CloudFormation resources) based on the event type:
    pull_request, push, or workflow_dispatch.
    """

    def execute(self) -> int:
        """
        Main entry point to detect changed CloudFormation resources, then write them to GITHUB_OUTPUT.
        Returns:
            int: Return code (0 - success, non-0 - error)
        """
        # Gather environment variables
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        github_token = os.environ.get("GITHUB_TOKEN", "")
        github_repository = os.environ.get("GITHUB_REPOSITORY", "")
        github_sha = os.environ.get("GITHUB_SHA", "")
        event_before = os.environ.get("GITHUB_EVENT_BEFORE", "")
        github_output = os.environ.get("GITHUB_OUTPUT", "")

        event_path = os.environ.get("GITHUB_EVENT_PATH")
        event_data = {}
        if event_path and os.path.exists(event_path):
            with open(event_path, 'r') as f:
                event_data = json.load(f)

        # Extract specific event data
        resource_path = None
        app_name = None
        pr_number = None
        pr_head_sha = None

        # workflow_dispatch
        if event_name == "workflow_dispatch":
            if "inputs" in event_data and "resource_path" in event_data["inputs"]:
                resource_path = event_data["inputs"]["resource_path"]
            # app_name might come from environment
            app_name = os.environ.get("INPUT_APP_NAME", "")

        # pull_request
        elif event_name == "pull_request":
            if "pull_request" in event_data:
                pr_number = event_data["pull_request"].get("number")
                if "head" in event_data["pull_request"]:
                    pr_head_sha = event_data["pull_request"]["head"].get("sha")

        # detect changed paths
        paths = self._detect_changed_applications(
            event_name=event_name,
            github_token=github_token,
            github_repository=github_repository,
            github_sha=github_sha,
            event_before=event_before,
            pr_number=pr_number,
            pr_head_sha=pr_head_sha,
            resource_path=resource_path,
            app_name=app_name
        )

        # Output the result
        if github_output:
            with open(github_output, 'a') as f:
                f.write(f"paths={paths}\n")
            self.log(f"Detected paths: {paths}")
        else:
            print(f"paths={paths}")

        return 0

    ###########################################################################
    #                       Internal Helper Methods                            #
    ###########################################################################
    def _log(self, message: str) -> None:
        """Simple log (similar to self.log but simpler)."""
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"{timestamp} - {message}")

    def _run_command(self, command: str) -> str:
        """Run a shell command and return the output."""
        try:
            result = subprocess.run(command, shell=True, check=True, text=True, capture_output=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            self.log(f"Command failed: {command}", "ERROR")
            self.log(f"Error: {e}", "ERROR")
            return ""

    def _get_changed_files_pull_request(self, github_token: str, repo: str,
                                        pr_number: int, head_sha: str) -> List[str]:
        """
        Get changed files from a pull request using git and GitHub API as a fallback.
        """
        # Try to get the SHA of the commit before the latest one
        prev_sha = self._run_command(f"git rev-parse {head_sha}^")

        if prev_sha:
            # Get changes from just the latest commit, not the entire PR
            changed_files = self._run_command(f"git diff --name-only {prev_sha} {head_sha}")
            if changed_files:
                return changed_files.splitlines()

        # Fallback to GitHub API
        api_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
        headers = {"Authorization": f"token {github_token}"}
        response = requests.get(api_url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                return [file['filename'] for file in data]

        # Final fallback
        return self._run_command("git diff --name-only HEAD~1 HEAD").splitlines()

    def _get_changed_files_push(self, before_sha: str, after_sha: str) -> List[str]:
        """Get changed files from a push event."""
        parent_count = self._run_command(f"git cat-file -p {after_sha} | grep -c '^parent '")

        try:
            parent_count = int(parent_count)
        except ValueError:
            parent_count = 0

        if parent_count > 1:
            merge_base = self._run_command(f"git merge-base {before_sha} {after_sha}")
            return self._run_command(f"git diff --name-only {merge_base} {after_sha}").splitlines()
        else:
            changed_files = self._run_command(f"git diff --name-only {before_sha} {after_sha}")
            if not changed_files:
                changed_files = self._run_command(f"git diff --name-only {before_sha}..{after_sha}")
            return changed_files.splitlines()

    def _detect_changed_applications(
        self,
        event_name: str,
        github_token: str,
        github_repository: str,
        github_sha: str,
        event_before: Optional[str] = None,
        pr_number: Optional[int] = None,
        pr_head_sha: Optional[str] = None,
        resource_path: Optional[str] = None,
        app_name: Optional[str] = None
    ) -> str:
        """Detect changed applications (cloud-formation paths)."""

        # For workflow_dispatch events
        if event_name == "workflow_dispatch" and resource_path:
            # Validate resource path against app_name if provided
            if app_name:
                expected_prefix = f"cloud-formation/{app_name}/"
                if not resource_path.startswith(expected_prefix):
                    self.log(f"ERROR: Resource path '{resource_path}' is not valid for app '{app_name}'", "ERROR")
                    self.log(f"Resource path must start with '{expected_prefix}'", "ERROR")
                    return ""
            return resource_path

        changed_paths = set()
        changed_files = []

        # Get changed files based on event type
        if event_name == "pull_request" and pr_number and pr_head_sha:
            changed_files = self._get_changed_files_pull_request(
                github_token, github_repository, pr_number, pr_head_sha
            )
        elif event_name == "push" and event_before:
            changed_files = self._get_changed_files_push(event_before, github_sha)
        else:
            changed_files = self._run_command("git diff --name-only HEAD~1 HEAD").splitlines()

        # Process changed files to find cloud-formation changes
        for file in changed_files:
            if not file:
                continue

            # Check if the file is a deployment config file
            if file.startswith("cloud-formation/") and (file.endswith(".yml") or file.endswith(".yaml")):
                path_dir = os.path.dirname(file)
                changed_paths.add(path_dir)

        # Convert set to comma-separated string
        paths = ",".join(sorted(changed_paths))

        # Debug info if no paths found
        if not paths:
            self.log("No cloud-formation paths detected. Debug information:", "WARNING")
            self.log(f"Event name: {event_name}", "WARNING")
            self.log(f"SHA: {github_sha}", "WARNING")
            self.log(f"Before: {event_before or 'N/A'}", "WARNING")

        return paths