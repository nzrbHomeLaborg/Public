#!/usr/bin/env python3
import os
import sys
import yaml
import json

def generate_matrix(config_path):
    # Отримання середовищ з оточення
    environments = os.environ.get('GITHUB_ENVIRONMENTS', 'dev,int,prod').split(',')
    
    # Завантаження конфігурації
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    
    # Ініціалізація матриць
    matrices = {
        'dev_matrix': {'include': []},
        'int_matrix': {'include': []},
        'prod_matrix': {'include': []},
        'custom_matrix': {'include': []}
    }
    
    # Обробка першого (і єдиного) deployments
    deployment = config.get('deployments', [{}])[0]
    
    # Обробка конфігурації
    for env in deployment.get('environments', []):
        if env not in environments:
            continue
        
        # Збирання параметрів для середовища
        matrix_item = {
            'environment': env,
            'runner': deployment.get('runners', {}).get(env, 'ubuntu-latest'),
            'github_environment': deployment.get('github_environments', {}).get(env),
            'aws_region': deployment.get('aws_regions', {}).get(env),
            'aws_role_secret': deployment.get('aws_role_secrets', {}).get(env),
            'cfn_role_secret': deployment.get('cfn_role_secrets', {}).get(env),
            'iam_role_secret': deployment.get('iam_execution_role_secrets', {}).get(env),
            'parameters': deployment.get('parameters', {}).get(env, {})
        }
        
        # Додавання до відповідної матриці
        if env == 'dev':
            matrices['dev_matrix']['include'].append(matrix_item)
        elif env == 'int':
            matrices['int_matrix']['include'].append(matrix_item)
        elif env == 'prod':
            matrices['prod_matrix']['include'].append(matrix_item)
        else:
            matrices['custom_matrix']['include'].append(matrix_item)
    
    return json.dumps(matrices)

def main():
    if len(sys.argv) < 2:
        print("Usage: python matrix_generator.py <config_path>")
        sys.exit(1)
    
    config_path = sys.argv[1]
    
    try:
        matrix = generate_matrix(config_path)
        print(matrix)
    except Exception as e:
        print(f"Error generating matrix: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()