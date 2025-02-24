"""
AI 开发助手配置文件
"""

import os
from pathlib import Path

# API配置
API_CONFIG = {
    'base_url': "https://zhenze-huhehaote.cmecloud.cn/inference-api/exp-api/inf-1336781912337387520/v1",
    'timeout': 120.0,
    'max_retries': 3,
    'retry_delay': 2,
    'max_api_calls': 10
}

# 模型配置
MODEL_CONFIG = {
    'model': "default",
    'temperature': 0.7,
    'max_tokens': 20480,
    'stream': True
}

# 系统提示配置
SYSTEM_PROMPTS = {
    'code_generation': """你是一个专业的Python程序员。
当用户请求创建项目时：
1. 你应该生成完整的、可运行的Python代码
2. 代码应该包含必要的注释和文档字符串
3. 代码应该遵循PEP 8规范
4. 需要包含主函数和程序入口点
5. 如果需要第三方库，请在代码开头注明依赖要求""",
    
    'code_review': "你是一个代码质量评估专家，擅长发现代码中的问题和改进空间。",
    'code_improvement': "你是一个代码优化专家，擅长提供具体的代码改进建议和实现方案。"
}

# 开发配置
DEV_CONFIG = {
    'min_improvement_score': 0.7,  # 最小改进分数阈值
    'max_iterations': 5,  # 最大迭代次数
    'auto_save': True,  # 自动保存功能
    'file_patterns': {'.py', '.js', '.java', '.cpp', '.h', '.hpp'}  # 支持的文件类型
}

# 输出配置
OUTPUT_CONFIG = {
    'buffer_size': 80,  # 输出缓冲区大小
    'show_thinking': True,  # 是否显示思考过程
    'save_history': True  # 是否保存历史记录
}

# 项目目录配置
class PathConfig:
    """项目路径配置"""
    ROOT_DIR = None
    OUTPUT_DIR = None
    HISTORY_DIR = None
    
    @classmethod
    def init_paths(cls, project_root):
        """初始化项目路径"""
        cls.ROOT_DIR = Path(project_root)
        cls.OUTPUT_DIR = cls.ROOT_DIR
        cls.HISTORY_DIR = cls.ROOT_DIR / "history"
        
        # 确保目录存在
        cls.ensure_dirs()
        return cls
    
    @classmethod
    def ensure_dirs(cls):
        """确保所有必要的目录存在"""
        if not all([cls.ROOT_DIR, cls.OUTPUT_DIR, cls.HISTORY_DIR]):
            raise ValueError("请先调用 init_paths 初始化路径配置")
            
        for dir_path in [cls.OUTPUT_DIR, cls.HISTORY_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)

# 提示模板
PROMPT_TEMPLATES = {
    'code_generation': """请创建一个Python项目，要求：
{prompt}

请按以下步骤回答：
1. 先思考项目的实现方案
2. 然后使用 ```python 和 ``` 包裹生成的代码
3. 代码需要包含：
   - 必要的导入语句
   - 类和函数的定义
   - 主函数和程序入口点
   - 注释和文档字符串""",

    'code_review': """请从以下几个方面评估代码质量，给出0-1的分数：
1. 代码结构和组织
2. 命名规范和代码风格
3. 错误处理和异常处理
4. 代码可读性和注释
5. 性能和效率

代码：
{code}""",

    'code_improvement': """请分析以下代码，提供具体的改进建议：

当前代码：
{code}

请给出具体的、可执行的改进建议，包括：
1. 代码结构优化
2. 性能改进
3. 代码风格完善
4. 功能增强"""
} 