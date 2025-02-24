"""
OpenAI玄幻小说冒险生成器 - 专业版
改进内容：
1. 增强型输入验证
2. 精细化异常处理
3. 可配置提示词模板
4. 扩展成就系统
5. 类型提示全覆盖
依赖：pip install openai python-dotenv termcolor
"""

import os
import sys
import time
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from termcolor import colored
import openai
from dotenv import load_dotenv
from functools import lru_cache

# 环境变量加载增强
ENV_LOADED = load_dotenv()
if not ENV_LOADED:
    print(colored("警告：未找到.env文件", "yellow"))

class ConfigError(Exception):
    """自定义配置异常"""

class StoryGenerationError(Exception):
    """自定义故事生成异常"""

class UserConfig:
    """增强型用户配置管理系统"""
    
    VALIDATORS = {
        'model': lambda x: x in {'gpt-3.5-turbo', 'gpt-4'},
        'temperature': lambda x: 0.0 <= x <= 2.0,
        'max_tokens': lambda x: 100 <= x <= 2000,
        'auto_save_interval': lambda x: x >= 1
    }
    
    def __init__(self, config_path: Path = Path("config.json")):
        self.config_path = config_path
        self.default_config = {
            'model': "gpt-3.5-turbo",
            'temperature': 0.8,
            'max_tokens': 1500,
            'auto_save_interval': 5,
            'max_history': 5,
            'language': "zh-CN"
        }
        self.config = self.load_or_init_config()
        
    def load_or_init_config(self) -> Dict:
        """加载或初始化配置文件"""
        try:
            if self.config_path.exists():
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return {**self.default_config, **config}
            return self.default_config.copy()
        except Exception as e:
            raise ConfigError(f"配置加载失败: {e}") from e
            
    def update_config(self, key: str, value: str) -> bool:
        """类型安全的配置更新"""
        if key not in self.default_config:
            raise ConfigError(f"无效配置项: {key}")
            
        original_type = type(self.default_config[key])
        try:
            converted = original_type(value)
        except ValueError as e:
            raise ConfigError(f"类型转换失败: {value} -> {original_type}") from e
            
        if key in self.VALIDATORS and not self.VALIDATORS[key](converted):
            raise ConfigError(f"无效值: {converted} for {key}")
            
        self.config[key] = converted
        self._save_config()
        return True
        
    def _save_config(self):
        """保存配置到文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            raise ConfigError(f"配置保存失败: {e}") from e

class StoryManager:
    """增强型故事状态管理器"""
    
    def __init__(self, config: UserConfig):
        self.story_history: List[Dict] = []
        self.current_chapter = 1
        self.config = config
        self.decision_points: List[Dict] = []
        self.achievements: Dict[str, Tuple[str, bool]] = {
            'first_blood': ('首次战斗胜利', False),
            'treasure_hunter': ('收集5件宝物', False),
            'immortal': ('连续10章无死亡', False)
        }
        self._prompt_template = self._load_prompt_template()
        self.last_save_time = 0.0
        
    def _load_prompt_template(self) -> str:
        """从文件加载提示词模板"""
        template_path = Path("prompt_template.txt")
        try:
            return template_path.read_text(encoding='utf-8')
        except FileNotFoundError:
            return """
            你是一个玄幻小说大师，请生成包含以下要素的冒险故事：
            1. 主角拥有特殊体质或金手指
            2. 包含至少三个创新修炼体系
            3. 每章必须有战斗情节和宝物获得
            4. 包含意想不到的剧情转折
            5. 对场景和功法进行详细描写
            请用{language}以{length}字左右的段落呈现，结尾给出2-3个选择分支
            """
        
    def generate_story_prompt(self, user_input: Optional[str] = None) -> List[Dict]:
        """构造带上下文的提示词"""
        system_content = self._prompt_template.format(
            language=self.config.config['language'],
            length=200
        )
        system_msg = {"role": "system", "content": system_content}
        
        messages = [system_msg]
        messages += self._get_recent_history()
        
        if user_input:
            sanitized_input = self._sanitize_input(user_input)
            messages.append({"role": "user", "content": sanitized_input})
        else:
            messages.append({"role": "user", "content": "请开始新的故事"})
            
        return messages
    
    def _get_recent_history(self) -> List[Dict]:
        """获取最近的上下文历史"""
        max_entries = self.config.config['max_history'] * 2
        return self.story_history[-max_entries:]
    
    @staticmethod
    def _sanitize_input(text: str) -> str:
        """输入内容消毒"""
        text = re.sub(r'[<>{}[\]]', '', text)  # 移除特殊符号
        return text[:500]  # 限制输入长度
        
    def save_progress(self, filename: str = "autosave.json") -> None:
        """增强型存档功能"""
        if time.time() - self.last_save_time < 60:  # 限制保存频率
            return
            
        save_data = {
            "chapter": self.current_chapter,
            "history": self.story_history,
            "decisions": self.decision_points,
            "achievements": [k for k, v in self.achievements.items() if v[1]]
        }
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False)
            self.last_save_time = time.time()
        except PermissionError as e:
            raise StoryGenerationError(f"文件权限错误: {e}") from e
        except IOError as e:
            raise StoryGenerationError(f"保存失败: {e}") from e

class OpenAIClient:
    """增强型API客户端"""
    
    RETRYABLE_ERRORS = (
        openai.error.RateLimitError,
        openai.error.APIConnectionError,
        openai.error.Timeout
    )
    
    def __init__(self, config: UserConfig):
        self.config = config
        openai.api_key = os.getenv("OPENAI_API_KEY", "")
        
    def generate_story(self, messages: List[Dict]) -> str:
        """带指数退避的重试机制"""
        max_retries = 5
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                response = openai.ChatCompletion.create(
                    model=self.config.config['model'],
                    messages=messages,
                    temperature=self.config.config['temperature'],
                    max_tokens=self.config.config['max_tokens'],
                    request_timeout=30
                )
                return response.choices[0].message['content'].strip()
            except self.RETRYABLE_ERRORS as e:
                delay = base_delay * (2 ** attempt)
                print(colored(f"API错误: {e}, {delay}秒后重试...", "yellow"))
                time.sleep(delay)
            except openai.error.InvalidRequestError as e:
                raise StoryGenerationError(f"无效请求: {e}") from e
        raise StoryGenerationError(f"API请求失败，已重试{max_retries}次")

class StoryFormatter:
    """增强型故事格式化"""
    
    COLOR_SCHEMES = {
        'zh-CN': {'text': 'white', 'choices': 'cyan'},
        'en-US': {'text': 'green', 'choices': 'yellow'}
    }
    
    @staticmethod
    @lru_cache(maxsize=100)
    def colorize(text: str, language: str = 'zh-CN') -> str:
        """带缓存的颜色格式化"""
        scheme = StoryFormatter.COLOR_SCHEMES.get(language, {})
        return colored(text, scheme.get('text', 'white'))
    
    @classmethod
    def display_story(cls, content: str, chapter: int, config: UserConfig) -> List[str]:
        """解析故事内容并返回选项列表"""
        print("\n" + colored("="*50, 'blue'))
        print(colored(f"📖 第{chapter}章 📖", 'yellow', attrs=['bold']))
        print(colored("-"*50, 'blue'))
        
        # 分割正文和选项
        parts = re.split(r'\n(?=选择\w?:)', content)
        body = parts[0]
        options = parts[1:] if len(parts) > 1 else []
        
        # 格式化正文
        paragraphs = [p.strip() for p in body.split('\n') if p.strip()]
        for para in paragraphs:
            print(cls.colorize(para, config.config['language']))
            
        # 处理选项
        valid_options = []
        for opt in options:
            if re.match(r'^选择[1-3]:', opt):
                print(colored(opt, cls.COLOR_SCHEMES[config.config['language']]['choices']))
                valid_options.append(opt)
                
        print(colored("="*50, 'blue'))
        return valid_options

class InputValidator:
    """输入验证增强类"""
    
    @staticmethod
    def validate_choice(input_str: str, options: List[str]) -> int:
        """验证用户选择有效性"""
        if not input_str.isdigit():
            raise ValueError("请输入数字")
            
        choice = int(input_str)
        if 1 <= choice <= len(options):
            return choice
        raise ValueError(f"无效选择，请输入1~{len(options)}之间的数字")
        
    @staticmethod
    def get_input_with_timeout(prompt: str, timeout: float = 30.0) -> str:
        """带超时的输入获取"""
        from threading import Timer
        import queue
        
        q = queue.Queue()
        t = Timer(timeout, q.put, args=('',))
        t.start()
        
        print(colored(prompt, 'green'), end='', flush=True)
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return ''
        finally:
            t.cancel()

# 主程序入口（完整实现需添加游戏循环逻辑）