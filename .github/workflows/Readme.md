# Secure Secret Handling in GitHub Actions Matrix Deployments

This document explains our approach for handling secrets with GitHub Actions matrix-based deployments for CloudFormation stacks.

## Challenge

We needed to solve a specific challenge:

- We use a matrix-based workflow for deploying CloudFormation stacks to multiple environments
- Parameters are defined in external configuration files
- Some parameters need to reference secrets
- GitHub Actions doesn't process `${{ secrets.NAME }}` expressions in values loaded from external files

## Our Solution

We implemented a secure file-based approach:

1. The workflow writes all available secrets to a temporary JSON file
2. Our Python parameter processor reads this file and loads the secrets into memory
3. Secret placeholders in parameters (e.g., `SECRET:NAME`) are replaced with actual values
4. The temporary file is immediately deleted after use
5. Processed parameters with actual secret values are written to a parameter file for CloudFormation

### Implementation

#### 1. Configuration File (deployment-config.yaml)

```yaml
deployments:
  - resource: my-resource
    environments:
      - dev
      - int
    # Other configuration...
    environment_secrets:
      dev:
        EMAIL: "NZRB"
      int:
        EMAIL: "INT_EMAIL"
    parameters:
      dev:
        stack-name: 'my-stack-dev'
        # Other parameters...
        inline-parameters:
          - ParameterKey: TopicName
            ParameterValue: my-topic-dev
          - ParameterKey: email
            ParameterValue: "SECRET:EMAIL"  # This will be replaced
```

#### 2. Workflow File

```yaml
- name: Set up secrets for parameter processing
  shell: bash
  run: |
    echo '${{ toJSON(secrets) }}' > /tmp/github_secrets.json
    echo "GITHUB_SECRETS_PATH=/tmp/github_secrets.json" >> $GITHUB_ENV
```

#### 3. Python Parameter Processor

```python
# Function to load secrets from file
def load_github_secrets():
    secrets = {}
    secrets_path = os.environ.get('GITHUB_SECRETS_PATH', '')
    
    if secrets_path and os.path.exists(secrets_path):
        try:
            with open(secrets_path, 'r') as f:
                secrets = json.load(f)
            # Delete file immediately after reading
            os.remove(secrets_path)
            return secrets
        except Exception as e:
            logger.error(f"Error reading secrets: {e}")
    
    return {}

# Later in the code
for param in inline_params:
    if isinstance(param["ParameterValue"], str) and param["ParameterValue"].startswith("SECRET:"):
        secret_name = param["ParameterValue"].replace("SECRET:", "")
        if secret_name in github_secrets:
            param["ParameterValue"] = github_secrets[secret_name]
```

## Alternative Approaches We Considered

We explored several other approaches, but each had limitations:

### 1. Direct Secret References in Configuration

```yaml
inline-parameters:
  - ParameterKey: email
    ParameterValue: "${{ secrets.NZRB }}"
```

**Why it doesn't work:** GitHub Actions doesn't evaluate expressions in values loaded from external files. The literal string `${{ secrets.NZRB }}` gets passed to the script instead of the actual secret value.

### 2. Base64 Encoded Secrets

```yaml
- name: Set up secrets
  run: |
    SECRETS_JSON='${{ toJSON(secrets) }}'
    SECRETS_BASE64=$(echo "$SECRETS_JSON" | base64 -w 0)
    echo "GITHUB_SECRETS_BASE64=$SECRETS_BASE64" >> $GITHUB_ENV
```

**Why we didn't choose it:** While it avoids writing secrets to disk, it exposes all secrets (albeit base64 encoded) in the logs, which is a security concern.

### 3. Individual Environment Variables

```yaml
- name: Set up specific secrets
  run: |
    echo "SECRET_NZRB=${{ secrets.NZRB }}" >> $GITHUB_ENV
    echo "SECRET_API_KEY=${{ secrets.API_KEY }}" >> $GITHUB_ENV
```

**Why we didn't choose it:** It works, but becomes cumbersome with many secrets across different environments, especially in a matrix setup. It lacks the flexibility of our chosen approach.

### 4. Custom JavaScript Action

Creating a custom action in JavaScript that utilizes GitHub Actions toolkit for secure secret handling.

**Why we didn't choose it:** Added complexity, development overhead, and potential limitations in processing complex parameters. Our Python-based approach integrates better with our existing tooling.

### 5. Non-Matrix Separate Workflows

Creating separate workflows for each environment without using matrices.

**Why we didn't choose it:** Lacks the scalability and maintainability benefits of our matrix-based approach. Would lead to significant duplication of workflow code.

## Security Considerations

Our file-based approach implements several security measures:

1. **Temporary file** - The secrets file exists only briefly during execution
2. **Immediate deletion** - File is deleted as soon as secrets are loaded into memory
3. **Isolated environment** - GitHub Actions runs in isolated environments that are destroyed after execution
4. **Memory-only processing** - After loading, secrets exist only in memory

## Usage Guide

### 1. Set Up Your Configuration

Create a deployment-config.yaml file:

```yaml
deployments:
  - resource: your-resource
    environments:
      - dev
    # Define runners, environments, etc.
    environment_secrets:
      dev:
        EMAIL: "YOUR_SECRET_NAME"  # Maps placeholder to actual secret name
    parameters:
      dev:
        stack-name: 'your-stack-name'
        # Other parameters...
        inline-parameters:
          - ParameterKey: SomeParameter
            ParameterValue: "SECRET:EMAIL"  # Will be replaced with actual secret
```

### 2. Configure Your Workflow

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    strategy:
      matrix: ${{ fromJSON(needs.prepare-matrices.outputs.dev_matrix) }}
    environment: ${{ matrix.github_environment }}
    
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
      
      # Write secrets to temporary file
      - name: Set up secrets for parameter processing
        shell: bash
        run: |
          echo '${{ toJSON(secrets) }}' > /tmp/github_secrets.json
          echo "GITHUB_SECRETS_PATH=/tmp/github_secrets.json" >> $GITHUB_ENV
      
      # Your deployment steps
      - name: Deploy Stack
        uses: ./.github/actions/your-deploy-action
        with:
          # Your parameters...
          inline-parameters: ${{ toJSON(matrix.parameters.inline-parameters) }}
```

### 3. Ensure Your Python Script Handles Secrets

Make sure your parameter processing script:

1. Reads the secret file path from `GITHUB_SECRETS_PATH`
2. Loads secrets from this file
3. Deletes the file immediately after reading
4. Replaces `SECRET:NAME` placeholders with actual values

## Conclusion

While our file-based approach has some security trade-offs, it provides the best balance of flexibility, security, and compatibility with our matrix-based deployment architecture. We've implemented appropriate safeguards to minimize security risks, and the approach integrates seamlessly with our existing deployment processes.