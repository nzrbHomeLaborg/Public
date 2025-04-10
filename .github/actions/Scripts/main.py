#!/usr/bin/env python3
"""
Модульная система Python для GitHub Actions.

Объединяет несколько скриптов в единую модульную структуру:
1. ParameterProcessor - обработка параметров CloudFormation
2. TagProcessor - обработка тегов для AWS ресурсов
3. DeploymentMatrixGenerator - генерация матриц развертывания
4. ChangeDetector - обнаружение измененных приложений

Использование:
python main.py parameter_processor [args]
python main.py tag_processor [args]
python main.py matrix_generator [args]
python main.py change_detector [args]
"""

import os
import sys
import json
import yaml
import re
import subprocess
import hashlib
import logging
import datetime
import requests
from pathlib import Path
from abc import ABC, abstractmethod
from typing import Dict, List, Set, Any, Optional, Tuple, Union
from datetime import datetime
import boto3
from botocore.exceptions import ClientError


class Action(ABC):
    """Базовый абстрактный класс для всех действий."""
    
    def __init__(self):
        """Инициализация логгера для действия."""
        self.logger = self._setup_logger()
    
    def _setup_logger(self) -> logging.Logger:
        """
        Настройка логгера.
        
        Returns:
            logging.Logger: Настроенный логгер
        """
        logger = logging.getLogger(self.__class__.__name__)
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger
    
    def log(self, message: str, level: str = "DEBUG") -> None:
        """
        Логирование сообщения с временной меткой и уровнем.
        
        Args:
            message: Сообщение для логирования
            level: Уровень логирования (INFO, WARNING, ERROR, DEBUG)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"{timestamp} [{level}] - {message}"
        
        if level == "ERROR":
            self.logger.error(full_message)
            # Вывод сообщения об ошибке в формате GitHub Actions
            print(f"::error::{message}")
        elif level == "WARNING":
            self.logger.warning(full_message)
            # Вывод предупреждения в формате GitHub Actions
            print(f"::warning::{message}")
        elif level == "DEBUG":
            self.logger.debug(full_message)
        else:
            self.logger.info(full_message)
    
    @abstractmethod
    def execute(self) -> int:
        """
        Выполнение действия.
        
        Returns:
            int: Код возврата (0 - успешно, не 0 - ошибка)
        """
        pass
    
    def write_output(self, key: str, value: str) -> None:
        """
        Запись результата в файл GITHUB_OUTPUT.
        
        Args:
            key: Ключ результата
            value: Значение результата
        """
        github_output = os.environ.get('GITHUB_OUTPUT')
        if github_output:
            try:
                if '\n' in value:
                    with open(github_output, 'a') as f:
                        f.write(f"{key}<<EOF\n{value}\nEOF\n")
                else:
                    with open(github_output, 'a') as f:
                        f.write(f"{key}={value}\n")
                self.log(f"Записан результат '{key}' в GITHUB_OUTPUT")
            except Exception as e:
                self.log(f"Ошибка при записи в GITHUB_OUTPUT: {str(e)}", "ERROR")
        else:
            self.log("Переменная GITHUB_OUTPUT не установлена", "WARNING")
            print(f"{key}={value}")


class ParameterProcessor(Action):
    """Обработка параметров для развертывания CloudFormation."""
    
    def execute(self) -> int:
        """
        Обработка параметров CloudFormation из файлов и JSON строк.
        
        Returns:
            int: Код возврата (0 - успешно, не 0 - ошибка)
        """
        self.log("Запуск обработки параметров CloudFormation")
        
        # Получение переменных окружения
        github_run_id = os.environ.get('GITHUB_RUN_ID', '')
        github_run_number = os.environ.get('GITHUB_RUN_NUMBER', '')
        parameter_file_path = os.environ.get('INPUT_PARAMETER_OVERRIDES', '')
        inline_parameters = os.environ.get('INPUT_INLINE_JSON_PARAMETERS', '').strip()
        
        # Загрузка секретов GitHub
        github_secrets = self._load_github_secrets()
        
        # Подготовка временного пути для вывода
        tmp_path = f"/tmp/{github_run_id}{github_run_number}"
        param_file = f"{tmp_path}/cfn-parameter-{github_run_id}-{github_run_number}.json"
        
        # Обработка параметров из файла
        combined_parameters = []
        if parameter_file_path:
            file_parameters = self._read_parameters_from_file(parameter_file_path)
            combined_parameters = self._process_file_parameters(file_parameters, github_secrets)
        
        # Обработка inline параметров
        if inline_parameters and inline_parameters != 'null':
            combined_parameters = self._process_inline_parameters(
                inline_parameters, combined_parameters, github_secrets
            )
        
        # Запись результатов в выходной файл
        if combined_parameters:
            return self._save_parameters(combined_parameters, tmp_path, param_file)
        else:
            self.write_output("PARAM_FILE", "")
            return 0
    
    def _load_github_secrets(self) -> Dict[str, str]:
        """
        Загрузка секретов GitHub.
        
        Returns:
            Dict[str, str]: Словарь с секретами GitHub
        """
        secrets = {}
        
        secrets_path = os.environ.get('GITHUB_SECRETS_PATH', '')
        salt_key = os.environ.get('SECRET_SALT_KEY', '')
        
        if not salt_key:
            self.log("SECRET_SALT_KEY не установлен, загрузка секретов из окружения")
            return self._load_secrets_from_env()
        
        if secrets_path and os.path.exists(secrets_path):
            try:
                key = hashlib.sha256(salt_key.encode()).hexdigest()
                
                try:
                    # Расшифровка файла секретов
                    result = subprocess.run(
                        ['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '10000', '-salt', 
                         '-in', secrets_path, 
                         '-pass', f'pass:{key}'],
                        capture_output=True, text=True, check=True
                    )
                    
                    secrets = json.loads(result.stdout)
                    self.log("Секреты успешно загружены из зашифрованного файла")
                    
                    try:
                        # Удаление файла секретов после загрузки
                        os.remove(secrets_path)
                        self.log(f"Файл секретов удален: {secrets_path}")
                    except Exception:
                        self.log(f"Не удалось удалить файл секретов: {secrets_path}", "WARNING")
                        
                except subprocess.CalledProcessError as e:
                    self.log(f"Ошибка расшифровки файла секретов: {e}", "ERROR")
                    
            except Exception as e:
                self.log(f"Ошибка при загрузке секретов: {e}", "ERROR")
        
        # Если секреты не удалось загрузить, попробуем из окружения
        if not secrets:
            secrets = self._load_secrets_from_env()
        
        return secrets
    
    def _load_secrets_from_env(self) -> Dict[str, str]:
        """
        Загрузка секретов из переменных окружения.
        
        Returns:
            Dict[str, str]: Словарь с секретами из переменных окружения
        """
        secrets = {}
        for key, value in os.environ.items():
            # Исключаем служебные переменные GitHub Actions
            if not key.startswith('GITHUB_') and not key.startswith('INPUT_'):
                secrets[key] = value
        
        self.log(f"Загружено {len(secrets)} секретов из переменных окружения")
        return secrets
    
    def _read_parameters_from_file(self, parameter_file_path: str) -> Dict[str, Any]:
        """
        Чтение параметров из файла (локального или S3).
        
        Args:
            parameter_file_path: Путь к файлу параметров
            
        Returns:
            Dict[str, Any]: Словарь с параметрами
        """
        if parameter_file_path.startswith('s3://'):
            self.log(f"Чтение параметров из S3: {parameter_file_path}")
            return self._read_from_s3(parameter_file_path)
        else:
            local_path = parameter_file_path.replace('file:///', '')
            self.log(f"Чтение параметров из локального файла: {local_path}")
            return self._read_from_local(local_path)
    
    def _read_from_s3(self, s3_path: str) -> Dict[str, Any]:
        """
        Чтение параметров из файла в S3.
        
        Args:
            s3_path: Путь к файлу в S3 (s3://bucket/key)
            
        Returns:
            Dict[str, Any]: Словарь с параметрами
        """
        try:
            path_parts = s3_path.replace('s3://', '').split('/', 1)
            bucket = path_parts[0]
            key = path_parts[1] if len(path_parts) > 1 else ''
            
            s3_client = boto3.client('s3')
            
            response = s3_client.get_object(Bucket=bucket, Key=key)
            
            content = response['Body'].read().decode('utf-8')
            
            try:
                return json.loads(content)
            except json.JSONDecodeError as e:
                self.log(f"Ошибка декодирования JSON из S3: {e}", "ERROR")
                return {}
                
        except ClientError as e:
            self.log(f"Ошибка S3 при чтении файла {s3_path}: {e}", "ERROR")
        except Exception as e:
            self.log(f"Неожиданная ошибка при чтении из S3: {e}", "ERROR")
        
        return {}
    
    def _read_from_local(self, file_path: str) -> Dict[str, Any]:
        """
        Чтение параметров из локального файла.
        
        Args:
            file_path: Путь к локальному файлу
            
        Returns:
            Dict[str, Any]: Словарь с параметрами
        """
        try:
            with open(file_path, 'r') as f:
                return json.loads(f.read())
        except FileNotFoundError:
            self.log(f"Файл не найден: {file_path}", "ERROR")
        except json.JSONDecodeError as e:
            self.log(f"Ошибка декодирования JSON из файла {file_path}: {e}", "ERROR")
        except Exception as e:
            self.log(f"Неожиданная ошибка при чтении файла {file_path}: {e}", "ERROR")
        
        return {}
    
    def _process_file_parameters(self, file_parameters: Dict[str, Any], 
                                github_secrets: Dict[str, str]) -> List[Dict[str, str]]:
        """
        Обработка параметров из файла.
        
        Args:
            file_parameters: Словарь с параметрами из файла
            github_secrets: Словарь с секретами GitHub
            
        Returns:
            List[Dict[str, str]]: Список параметров для CloudFormation
        """
        if not file_parameters:
            return []
        
        combined_parameters = []
        
        # Формат с массивом объектов ParameterKey/ParameterValue
        if isinstance(file_parameters, list):
            self.log("Обнаружен формат параметров в виде списка")
            for param in file_parameters:
                if isinstance(param.get("ParameterValue"), str) and param["ParameterValue"].startswith("SECRET:"):
                    secret_name = param["ParameterValue"].replace("SECRET:", "")
                    if secret_name in github_secrets:
                        param["ParameterValue"] = github_secrets[secret_name]
                        self.log(f"Применен секрет {secret_name} к параметру {param.get('ParameterKey', '')}")
            combined_parameters = file_parameters
        
        # Формат с плоским словарем ключ/значение
        else:
            self.log("Обнаружен формат параметров в виде словаря")
            parameter_dict = {}
            for key, value in file_parameters.items():
                if isinstance(value, str) and value.startswith("SECRET:"):
                    secret_name = value.replace("SECRET:", "")
                    if secret_name in github_secrets:
                        parameter_dict[key] = github_secrets[secret_name]
                        self.log(f"Применен секрет {secret_name} к параметру {key}")
                    else:
                        parameter_dict[key] = value
                else:
                    parameter_dict[key] = value
           
            # Преобразуем словарь в формат для CloudFormation
            for key, value in parameter_dict.items():
                combined_parameters.append({
                    "ParameterKey": key,
                    "ParameterValue": value
                })
        
        self.log(f"Обработано {len(combined_parameters)} параметров из файла")
        return combined_parameters
    
    def _process_inline_parameters(self, inline_parameters: str, 
                                 combined_parameters: List[Dict[str, str]],
                                 github_secrets: Dict[str, str]) -> List[Dict[str, str]]:
        """
        Обработка inline параметров из JSON строки.
        
        Args:
            inline_parameters: JSON строка с параметрами
            combined_parameters: Текущий список параметров
            github_secrets: Словарь с секретами GitHub
            
        Returns:
            List[Dict[str, str]]: Обновленный список параметров
        """
        try:
            inline_params = json.loads(inline_parameters)
            self.log(f"Успешно разобраны inline параметры: {type(inline_params)}")
            
            # Конвертация из словаря в список, если нужно
            if not isinstance(inline_params, list):
                self.log("Конвертация inline параметров из словаря в список")
                inline_params_list = []
                for key, value in inline_params.items():
                    inline_params_list.append({
                        "ParameterKey": key,
                        "ParameterValue": value
                    })
                inline_params = inline_params_list
            
            # Создаем словарь для быстрого поиска существующих параметров
            existing_params = {param["ParameterKey"]: i for i, param in enumerate(combined_parameters)}
            
            # Обрабатываем каждый inline параметр
            for param in inline_params:
                key = param["ParameterKey"]

                # Подставляем секреты, если необходимо
                if isinstance(param["ParameterValue"], str) and param["ParameterValue"].startswith("SECRET:"):
                    secret_name = param["ParameterValue"].replace("SECRET:", "")
                    if secret_name in github_secrets:
                        param["ParameterValue"] = github_secrets[secret_name]
                        self.log(f"Применен секрет {secret_name} к inline параметру {key}")
                
                # Обновляем или добавляем параметр
                if key in existing_params:
                    combined_parameters[existing_params[key]] = param
                    self.log(f"Обновлен параметр {key}")
                else:
                    combined_parameters.append(param)
                    self.log(f"Добавлен новый параметр {key}")
            
            self.log(f"Всего параметров после обработки inline: {len(combined_parameters)}")
            return combined_parameters
                
        except json.JSONDecodeError as e:
            self.log(f"Ошибка разбора JSON inline параметров: {e}", "ERROR")
            if not combined_parameters:
                self.log("Нет параметров после обработки", "ERROR")
            return combined_parameters
    
    def _save_parameters(self, combined_parameters: List[Dict[str, str]], 
                       tmp_path: str, param_file: str) -> int:
        """
        Сохранение параметров в JSON файл.
        
        Args:
            combined_parameters: Список параметров
            tmp_path: Временный путь для файла
            param_file: Полный путь к файлу параметров
            
        Returns:
            int: Код возврата (0 - успешно, не 0 - ошибка)
        """
        try:
            Path(tmp_path).mkdir(parents=True, exist_ok=True)
            with open(param_file, 'w') as f:
                json.dump(combined_parameters, f, indent=2)
            self.log(f"Параметры сохранены в {param_file}")
            
            # Запись пути к файлу параметров в вывод
            self.write_output("PARAM_FILE", f"file:///{param_file}")
            return 0
        except Exception as e:
            self.log(f"Ошибка при сохранении параметров: {e}", "ERROR")
            return 1


class TagProcessor(Action):
    """Обработка тегов для AWS ресурсов."""
    
    def execute(self) -> int:
        """
        Обработка тегов из различных источников и форматов.
        
        Returns:
            int: Код возврата (0 - успешно, не 0 - ошибка)
        """
        self.log("Запуск обработки тегов для AWS ресурсов")
        
        # Получение входных данных из переменных среды
        tags_json = os.environ.get('INPUT_TAGS', '')
        tags_key_value = os.environ.get('INPUT_TAGS_KEY_VALUE', '')
        
        # Инициализация пустого списка тегов
        combined_tags = []
        
        # Обработка JSON-тегов
        if tags_json:
            combined_tags = self._process_json_tags(tags_json, combined_tags)
        
        # Обработка тегов в формате ключ-значение
        if tags_key_value:
            combined_tags = self._process_key_value_tags(tags_key_value, combined_tags)
        
        # Проверка, есть ли теги
        if not combined_tags:
            error_message = ("No tags are provided for this stack. Please follow "
                           "the AWS tagging guidelines (https://catdigital.atlassian.net/wiki/spaces/CD/pages/105349296/AWS+Tagging).")
            self.log(error_message, "ERROR")
            return 1
        
        # Запись результатов
        self.write_output("TAGS", json.dumps(combined_tags))
        self.log(f"Обработано и сохранено {len(combined_tags)} тегов")
        return 0
    
    def _process_json_tags(self, tags_json: str, 
                         combined_tags: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Обработка тегов из JSON строки.
        
        Args:
            tags_json: JSON строка с тегами
            combined_tags: Текущий список тегов
            
        Returns:
            List[Dict[str, str]]: Обновленный список тегов
        """
        try:
            json_tags = json.loads(tags_json)
            self.log(f"Успешно разобраны JSON теги, найдено {len(json_tags)} тегов")
            combined_tags.extend(json_tags)
            return combined_tags
        except json.JSONDecodeError as e:
            self.log(f"Ошибка разбора JSON тегов: {e}", "WARNING")
            return combined_tags
    
    def _process_key_value_tags(self, tags_key_value: str, 
                              combined_tags: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Обработка тегов в формате ключ-значение.
        
        Args:
            tags_key_value: Строка с тегами в формате ключ=значение
            combined_tags: Текущий список тегов
            
        Returns:
            List[Dict[str, str]]: Обновленный список тегов
        """
        # Создаем словарь существующих тегов для быстрого поиска
        existing_tags = {tag["Key"]: i for i, tag in enumerate(combined_tags)}
        
        # Разбор строки по строкам
        tag_lines = [line.strip() for line in tags_key_value.splitlines()]
        processed_count = 0
        
        for line in tag_lines:
            # Пропускаем пустые строки и комментарии
            if not line or line.startswith('#'):
                continue
            
            # Разбор строки в формате ключ=значение
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Удаление кавычек, если они есть
                value = re.sub(r'^["\'](.*)["\']$', r'\1', value)
                
                # Если ключ уже существует, заменяем значение
                if key in existing_tags:
                    combined_tags[existing_tags[key]] = {
                        "Key": key,
                        "Value": value
                    }
                    self.log(f"Обновлен тег: {key}={value}")
                else:
                    # Добавляем новый тег
                    combined_tags.append({
                        "Key": key,
                        "Value": value
                    })
                    existing_tags[key] = len(combined_tags) - 1
                    self.log(f"Добавлен тег: {key}={value}")
                
                processed_count += 1
        
        self.log(f"Обработано {processed_count} тегов в формате ключ-значение")
        return combined_tags


class DeploymentMatrixGenerator(Action):
    """Генерация матриц развертывания для различных окружений."""
    
    def execute(self) -> int:
        """
        Генерация матриц развертывания на основе конфигурационных файлов.
        
        Returns:
            int: Код возврата (0 - успешно, не 0 - ошибка)
        """
        self.log("Запуск генерации матриц развертывания")
        
        # Инициализация пустых списков для элементов матрицы
        dev_matrix_items = []
        int_matrix_items = []
        prod_matrix_items = []
        custom_matrix_items = []
        
        # Получение входных параметров из переменных среды
        resource_paths = os.environ.get("INPUT_RESOURCE_PATHS", "")
        specific_environment = os.environ.get("INPUT_SPECIFIC_ENVIRONMENT", "")
        
        self.log(f"Входные пути ресурсов: {resource_paths}")
        self.log(f"Указанное окружение: {specific_environment}")
        
        # Получение пути к файлу для вывода GitHub Actions
        github_output = os.environ.get("GITHUB_OUTPUT", "")
        if not github_output:
            self.log("Переменная GITHUB_OUTPUT не установлена", "ERROR")
            return 1
        
        # Разбор входных путей ресурсов
        if not resource_paths:
            self.log("Пути ресурсов не указаны")
            resource_paths_list = []
        else:
            resource_paths_list = [path.strip() for path in resource_paths.split(',') if path.strip()]
            self.log(f"Обработка {len(resource_paths_list)} путей ресурсов")
        
        # Обработка каждого пути ресурса
        for resource_path in resource_paths_list:
            matrix_items = self._process_resource_path(resource_path, specific_environment)
            
            # Добавление элементов в соответствующие матрицы
            dev_matrix_items.extend(matrix_items["dev"])
            int_matrix_items.extend(matrix_items["int"])
            prod_matrix_items.extend(matrix_items["prod"])
            custom_matrix_items.extend(matrix_items["custom"])
        
        # Создание матриц для различных окружений
        dev_matrix_json = {"include": dev_matrix_items}
        int_matrix_json = {"include": int_matrix_items}
        prod_matrix_json = {"include": prod_matrix_items}
        custom_matrix_json = {"include": custom_matrix_items}
        
        # Логирование сводки по матрицам
        self.log(f"Сводка по сгенерированным матрицам:")
        self.log(f"  - dev matrix: {len(dev_matrix_items)} элементов")
        self.log(f"  - int matrix: {len(int_matrix_items)} элементов")
        self.log(f"  - prod matrix: {len(prod_matrix_items)} элементов")
        self.log(f"  - custom matrix: {len(custom_matrix_items)} элементов")
        
        # Преобразование матриц в JSON строки
        try:
            dev_matrix_str = json.dumps(dev_matrix_json, ensure_ascii=False)
            int_matrix_str = json.dumps(int_matrix_json, ensure_ascii=False)
            prod_matrix_str = json.dumps(prod_matrix_json, ensure_ascii=False)
            custom_matrix_str = json.dumps(custom_matrix_json, ensure_ascii=False)
            self.log("Матрицы успешно преобразованы в JSON")
        except Exception as e:
            self.log(f"Ошибка преобразования матриц в JSON: {str(e)}", "ERROR")
            return 1
        
        # Запись матриц в GITHUB_OUTPUT
        with open(github_output, 'a') as f:
            f.write(f"dev_matrix<<EOF\n{dev_matrix_str}\nEOF\n")
            f.write(f"int_matrix<<EOF\n{int_matrix_str}\nEOF\n")
            f.write(f"prod_matrix<<EOF\n{prod_matrix_str}\nEOF\n")
            f.write(f"custom_matrix<<EOF\n{custom_matrix_str}\nEOF\n")
        
        self.log("Матрицы успешно записаны в GITHUB_OUTPUT")
        return 0
    
    def _process_resource_path(self, resource_path: str, 
                             specific_environment: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Обработка пути ресурса для извлечения конфигураций развертывания.
        
        Args:
            resource_path: Путь к ресурсу CloudFormation
            specific_environment: Опциональное конкретное окружение для фильтрации
            
        Returns:
            Dict[str, List[Dict[str, Any]]]: Словарь с элементами матрицы для каждого типа окружения
        """
        self.log(f"Обработка пути ресурса: {resource_path}")
        
        # Инициализация пустых списков для элементов матрицы
        matrix_items = {
            "dev": [],
            "int": [],
            "prod": [],
            "custom": []
        }
        
        # Проверка обоих расширений: YAML и YML
        config_path = f"{resource_path}/deployment-config.yaml"
        if not os.path.isfile(config_path):
            config_path = f"{resource_path}/deployment-config.yml"
            if not os.path.isfile(config_path):
                self.log(f"Конфигурационный файл не найден для {resource_path}", "WARNING")
                return matrix_items
        
        # Чтение YAML конфигурационного файла
        self.log(f"Чтение YAML конфигурации из {config_path}")
        config_content = self._load_yaml_config(config_path)
        
        # Проверка структуры конфигурации
        if not config_content or not isinstance(config_content, dict):
            self.log(f"Неверная структура YAML в {config_path}", "WARNING")
            return matrix_items
        
        # Извлечение имени приложения и ресурса из пути
        app = os.path.dirname(resource_path)
        resource = os.path.basename(resource_path)
        
        self.log(f"Используется APP={app} и RESOURCE={resource}")
        
        # Получение конфигураций развертывания
        deployments = config_content.get('deployments', [])
        if not deployments or not isinstance(deployments, list) or len(deployments) == 0:
            self.log(f"Конфигурации развертывания не найдены в {config_path}", "WARNING")
            return matrix_items
        
        # Получение списка окружений
        environments = deployments[0].get('environments', [])
        if not environments:
            self.log(f"Окружения не найдены в {config_path}", "WARNING")
            return matrix_items
        
        self.log(f"Найдены окружения: {' '.join(environments)}")
        
        # Фильтрация по конкретному окружению, если указано
        if specific_environment:
            environments = self._filter_environments(environments, specific_environment, config_path)
            if not environments:
                return matrix_items
        
        # Обработка каждого окружения для этого ресурса
        for env in environments:
            matrix_item = self._process_environment(env, resource_path, app, resource, deployments[0], config_path)
            if matrix_item:
                # Добавление в соответствующую матрицу на основе окружения
                if env == "dev":
                    matrix_items["dev"].append(matrix_item)
                    self.log(f"Добавлено в dev матрицу: {app}/{resource}")
                elif env == "int":
                    matrix_items["int"].append(matrix_item)
                    self.log(f"Добавлено в int матрицу: {app}/{resource}")
                elif env == "prod":
                    matrix_items["prod"].append(matrix_item)
                    self.log(f"Добавлено в prod матрицу: {app}/{resource}")
                
                # Добавление в матрицу пользовательского развертывания, если включено
                custom_deployment = str(matrix_item.get("parameters", {}).get("custom_deployment", "false")).lower()
                if custom_deployment == "true":
                    matrix_items["custom"].append(matrix_item)
                    self.log(f"Добавлено в custom матрицу: {app}/{resource}")
        
        return matrix_items
    
    def _filter_environments(self, environments: List[str], specific_environment: str, 
                           config_path: str) -> List[str]:
        """
        Фильтрация окружений на основе specific_environment.
        
        Args:
            environments: Список доступных окружений
            specific_environment: Окружение(я) для фильтрации (разделенные запятыми)
            config_path: Путь к файлу конфигурации (для сообщений предупреждений)
            
        Returns:
            List[str]: Отфильтрованный список окружений
        """
        if ',' in specific_environment:
            # Указано несколько окружений
            selected_envs = [env.strip() for env in specific_environment.split(',') if env.strip()]
            self.log(f"Выбрано несколько окружений: {selected_envs}")
            
            # Создание регулярного выражения для сопоставления
            selected_envs_pattern = f"^({'|'.join(selected_envs)})$"
            self.log(f"Шаблон регулярного выражения: {selected_envs_pattern}")
            
            # Фильтрация окружений
            filtered_environments = []
            for env_candidate in environments:
                if re.match(selected_envs_pattern, env_candidate):
                    filtered_environments.append(env_candidate)
                    self.log(f"Выбрано окружение: {env_candidate}")
            
            if not filtered_environments:
                self.log(f"Ни одно из указанных окружений не найдено в {config_path}", "WARNING")
                return []
            
            self.log(f"Отфильтрованные окружения: {' '.join(filtered_environments)}")
            return filtered_environments
        else:
            # Указано одно окружение
            if specific_environment in environments:
                self.log(f"Выбрано одно окружение: {specific_environment}")
                return [specific_environment]
            else:
                self.log(f"Указанное окружение не найдено в {config_path}", "WARNING")
                return []
    
    def _process_environment(self, env: str, resource_path: str, app: str, resource: str, 
                           deployment: Dict[str, Any], config_path: str) -> Optional[Dict[str, Any]]:
        """
        Обработка одного окружения для ресурса.
        
        Args:
            env: Имя окружения (dev, int, prod)
            resource_path: Путь к ресурсу CloudFormation
            app: Имя приложения
            resource: Имя ресурса
            deployment: Конфигурация развертывания
            config_path: Путь к файлу конфигурации
            
        Returns:
            Optional[Dict[str, Any]]: Элемент матрицы или None, если отсутствуют обязательные поля
        """
        self.log(f"Обработка окружения: {env} для {resource_path}")
        
        # Извлечение параметров
        params = deployment.get('parameters', {}).get(env, {})
        runner = deployment.get('runners', {}).get(env)
        gh_env = deployment.get('github_environments', {}).get(env)
        aws_region = deployment.get('aws_regions', {}).get(env)
        aws_role_secret = deployment.get('aws_role_secrets', {}).get(env, "AWS_ROLE_TO_ASSUME")
        cfn_role_secret = deployment.get('cfn_role_secrets', {}).get(env, "CFN_ROLE_ARN")
        iam_role_secret = deployment.get('iam_execution_role_secrets', {}).get(env, "IAM_EXECUTION_ROLE_ARN")
        vars_config = deployment.get('github_vars', {}).get(env, {})
        secret_pass = params.get('secret_pass', False)
        
        # Проверка, включено ли пользовательское развертывание для этого окружения
        custom_deployment = str(params.get('custom_deployment', "false")).lower()
        self.log(f"Пользовательское развертывание для {env}: {custom_deployment}")
        
        # Пропуск, если отсутствуют обязательные поля
        if (not params or params is None or 
            not runner or runner is None or 
            not gh_env or gh_env is None or 
            not aws_region or aws_region is None):
            self.log(f"Отсутствуют обязательные конфигурации для {resource_path} в окружении {env}", "WARNING")
            self.log(f"Params: {params is not None}, Runner: {runner is not None}, " +
                f"GitHub Env: {gh_env is not None}, AWS Region: {aws_region is not None}")
            return None
        
        # Создание элемента матрицы
        matrix_item = {
            "application": app,
            "resource": resource,
            "environment": env,
            "runner": runner,
            "github_environment": gh_env,
            "aws_region": aws_region,
            "aws_role_secret": aws_role_secret,
            "cfn_role_secret": cfn_role_secret,
            "iam_role_secret": iam_role_secret,
            "github_vars": vars_config,
            "secret_pass": secret_pass,
            "parameters": params
        }
        
        self.log(f"Создан элемент матрицы для {resource_path} в окружении {env}")
        return matrix_item
    
    def _load_yaml_config(self, file_path: str) -> Dict[str, Any]:
        """
        Загрузка YAML-конфигурации из файла.
        
        Args:
            file_path: Путь к YAML-файлу конфигурации
            
        Returns:
            Dict[str, Any]: Словарь с конфигурацией или пустой словарь при ошибке загрузки
        """
        self.log(f"Попытка загрузки YAML-файла: {file_path}")
        try:
            with open(file_path, 'r') as file:
                config = yaml.safe_load(file)
                self.log(f"YAML-файл успешно загружен: {file_path}")
                return config
        except FileNotFoundError:
            self.log(f"Файл не найден: {file_path}", "ERROR")
            return {}
        except yaml.YAMLError as e:
            self.log(f"Ошибка разбора YAML-файла {file_path}: {str(e)}", "ERROR")
            return {}
        except Exception as e:
            self.log(f"Непредвиденная ошибка при загрузке YAML-файла {file_path}: {str(e)}", "ERROR")
            return {}