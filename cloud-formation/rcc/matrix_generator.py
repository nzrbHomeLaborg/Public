import os
import yaml
import json
import argparse

def get_github_secrets():
    """
    Отримання секретів для всіх можливих середовищ.
    """
    # Отримуємо всі можливі середовища з вхідних даних
    environments = os.environ.get('GITHUB_ENVIRONMENTS', '').split(',')
    
    # Словник для зберігання секретів за середовищами
    all_secrets = {}

    for env in environments:
        env = env.strip().lower()
        if not env:
            continue

        # Збираємо секрети для кожного середовища
        env_secrets = {}
        for key, value in os.environ.items():
            # Шукаємо секрети специфічні для конкретного середовища
            if key.startswith(f'{env.upper()}_SECRET_'):
                secret_name = key[len(f'{env.upper()}_SECRET_'):]
                env_secrets[secret_name] = value
        
        all_secrets[env] = env_secrets

    return all_secrets

def load_deployment_config(config_path):
    """Завантаження конфігураційного файлу."""
    with open(config_path, 'r') as file:
        return yaml.safe_load(file)

def replace_secrets(params, secrets):
    """Заміна плейсхолдерів секретів на реальні значення."""
    def replace_secret_in_value(value):
        if isinstance(value, str) and value.startswith('${{ secrets.'):
            secret_name = value.split('secrets.')[1].rstrip(' }}')
            return secrets.get(secret_name, value)
        return value

    if isinstance(params, dict):
        return {k: replace_secret_in_value(v) for k, v in params.items()}
    elif isinstance(params, list):
        return [replace_secret_in_value(item) for item in params]
    
    return params

def generate_matrix(config, all_secrets):
    """Генерація матриці для розгортання."""
    matrix_items = []

    for deployment in config.get('deployments', []):
        for env in deployment.get('environments', []):
            # Секрети для поточного середовища
            env_secrets = all_secrets.get(env, {})
            
            # Збираємо параметри для поточного середовища
            env_params = deployment.get('parameters', {}).get(env, {})
            
            # Заміна секретів
            env_params = replace_secrets(env_params, env_secrets)

            matrix_item = {
                'environment': env,
                'runner': deployment.get('runners', {}).get(env),
                'github_environment': deployment.get('github_environments', {}).get(env),
                'aws_region': deployment.get('aws_regions', {}).get(env),
                'parameters': env_params
            }

            matrix_items.append(matrix_item)

    return matrix_items

def main():
    parser = argparse.ArgumentParser(description='Generate deployment matrix')
    parser.add_argument('config_path', help='Path to deployment configuration file')
    args = parser.parse_args()

    # Перевірка, чи існує файл
    if not os.path.exists(args.config_path):
        print(f"Error: Configuration file not found at {args.config_path}")
        sys.exit(1)

    # Завантаження конфігурації
    config = load_deployment_config(args.config_path)

    # Отримання секретів для всіх середовищ
    all_secrets = get_github_secrets()

    # Генерація матриці
    matrix = generate_matrix(config, all_secrets)

    # Виведення JSON для GitHub Actions
    result = {
        'dev_matrix': {'include': [item for item in matrix if item['environment'] == 'dev']},
        'int_matrix': {'include': [item for item in matrix if item['environment'] == 'int']},
        'prod_matrix': {'include': [item for item in matrix if item['environment'] == 'prod']},
        'custom_matrix': {'include': [item for item in matrix if item['environment'] not in ['dev', 'int', 'prod']]}
    }

    print(json.dumps(result))