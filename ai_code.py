import os
import sys
import re

import json
import time
import requests
import hashlib
from pathlib import Path
from typing import Dict, List, Set, Iterator
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import (
    API_CONFIG, 
    MODEL_CONFIG, 
    SYSTEM_PROMPTS, 
    DEV_CONFIG, 
    OUTPUT_CONFIG,
    PathConfig,
    PROMPT_TEMPLATES
)

class CodeFileManager:
    def __init__(self, root_dir: str, file_patterns: Set[str] = None):
        self.root_dir = Path(root_dir)
        self.file_patterns = file_patterns or {'.py', '.js', '.java', '.cpp', '.h', '.hpp'}
        self.file_cache: Dict[str, str] = {}  # 文件路径 -> 文件哈希
        self.scan_files()

    def scan_files(self) -> Dict[str, str]:
        """扫描目录下的所有代码文件"""
        new_cache = {}
        for file_path in self._find_code_files():
            try:
                file_hash = self._calculate_file_hash(file_path)
                new_cache[str(file_path)] = file_hash
            except Exception as e:
                print(f"⚠️ 扫描文件失败 {file_path}: {e}")
        return new_cache

    def _find_code_files(self) -> List[Path]:
        """查找所有代码文件"""
        code_files = []
        for pattern in self.file_patterns:
            code_files.extend(self.root_dir.rglob(f"*{pattern}"))
        return code_files

    def _calculate_file_hash(self, file_path: Path) -> str:
        """计算文件哈希值"""
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def get_modified_files(self) -> Dict[str, str]:
        """获取已修改的文件"""
        new_cache = self.scan_files()
        modified_files = {}
        
        # 检查新增和修改的文件
        for file_path, new_hash in new_cache.items():
            if file_path not in self.file_cache or self.file_cache[file_path] != new_hash:
                modified_files[file_path] = 'modified'
        
        # 检查删除的文件
        for file_path in self.file_cache:
            if file_path not in new_cache:
                modified_files[file_path] = 'deleted'
        
        self.file_cache = new_cache
        return modified_files

class AIIterativeDeveloper:
    def __init__(self, api_key, initial_prompt, base_url=None):
        # 初始化OpenAI客户端
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or API_CONFIG['base_url'],
            timeout=API_CONFIG['timeout']
        )
        
        # 初始化配置
        self.config = {
            **MODEL_CONFIG,
            **DEV_CONFIG,
            'current_api_calls': 0
        }
        
        self.system_prompts = SYSTEM_PROMPTS
        self.output_config = OUTPUT_CONFIG
        
        # 初始化项目状态
        self.project_state = {
            'code': {},
            'current_code': initial_prompt,
            'version': 0,
            'history': [],
            'user_feedback': []
        }
        
        self.file_manager = None  # 初始化为None，等待后续设置

    def _stream_output(self, response_iterator: Iterator) -> str:
        """处理流式输出，实时显示思考过程和代码"""
        full_response = []
        code_content = []
        in_code_block = False
        buffer = ""
        
        try:
            for chunk in response_iterator:
                if hasattr(chunk.choices[0].delta, 'content') and chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    buffer += content
                    full_response.append(content)
                    
                    # 当遇到换行或buffer达到一定长度时输出
                    if '\n' in buffer or len(buffer) > 80:
                        print(buffer, end='', flush=True)
                        
                        # 检测代码块
                        if "```python" in buffer:
                            in_code_block = True
                            buffer = ""
                            continue
                        elif "```" in buffer and in_code_block:
                            in_code_block = False
                            buffer = ""
                            continue
                        
                        # 收集代码内容
                        if in_code_block:
                            code_content.append(buffer)
                            
                        buffer = ""
            
            # 处理剩余的buffer
            if buffer:
                print(buffer, end='', flush=True)
                if in_code_block:
                    code_content.append(buffer)
                
            print("\n")  # 输出完成后换行
            
            # 提取代码内容
            code = ''.join(code_content).strip()
            if not code:
                # 尝试从完整响应中提取代码块
                full_text = ''.join(full_response)
                if "```python" in full_text:
                    code_blocks = full_text.split("```python")
                    if len(code_blocks) > 1:
                        code = code_blocks[1].split("```")[0].strip()
            
            if not code:
                raise ValueError("No code block found in response")
            
            return code
            
        except Exception as e:
            print(f"\n⚠️ 流输出错误：{str(e)}")
            raise

    def _build_code_generation_prompt(self, improvement_goals: str) -> str:
        """构建更完整的代码生成提示"""
        return (
            "请生成完整的Python代码。要求：\n"
            "1. 必须包含完整的导入语句\n"
            "2. 必须包含详细的文档字符串，说明功能和依赖\n"
            "3. 必须包含所有必要的类型注解\n"
            "4. 必须实现完整的错误处理\n"
            "5. 代码结构必须完整，不能省略任何部分\n\n"
            f"需求：\n{improvement_goals}\n\n"
            "请按以下格式输出：\n"
            "1. 代码说明：[功能说明]\n"
            "2. 完整代码：\n"
            "```python\n"
            "[包含所有必要组件的完整代码]\n"
            "```\n"
            "3. 使用说明：[如何使用这段代码]"
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=4, max=60),
        retry=retry_if_exception_type((requests.exceptions.RequestException, json.JSONDecodeError, ValueError)),
        reraise=True
    )
    def call_ai_api(self, prompt):
        """调用AI接口生成完整代码"""
        try:
            prompt_text = self._build_code_generation_prompt(prompt)
            
            print("\n🔄 正在生成完整代码...", flush=True)
            
            response = self.client.chat.completions.create(
                model=self.config['model'],
                messages=[
                    {
                        "role": "system", 
                        "content": (
                            "你是一个专业的Python开发者。请确保：\n"
                            "1. 生成的代码必须是完整的，包含所有必要组件\n"
                            "2. 包含完整的类型注解和错误处理\n"
                            "3. 提供清晰的文档和注释\n"
                            "4. 遵循最佳实践和设计模式\n"
                            "5. 代码必须可以直接运行，不能有省略部分"
                        )
                    },
                    {"role": "user", "content": prompt_text}
                ],
                temperature=self.config['temperature'],
                max_tokens=self.config['max_tokens'],
                stream=True,
                timeout=120
            )
            
            self.config['current_api_calls'] += 1
            return self._stream_output(response)
            
        except requests.exceptions.Timeout:
            print("\n⚠️ API请求超时，正在重试...")
            raise
        except requests.exceptions.RequestException as e:
            print(f"\n❌ API网络错误：{str(e)}")
            raise
        except Exception as e:
            print(f"\n❌ API调用错误：{str(e)}")
            if hasattr(e, 'response'):
                print(f"响应状态码: {e.response.status_code}")
                print(f"响应内容: {e.response.text}")
            raise

    def init_file_manager(self, project_root):
        """初始化文件管理器和路径配置"""
        try:
            # 先初始化路径配置
            PathConfig.init_paths(project_root)
            
            # 然后初始化文件管理器
            self.file_manager = CodeFileManager(project_root)
            
            print(f"📂 已初始化项目目录：{project_root}")
            print(f"   - 输出目录：{PathConfig.OUTPUT_DIR}")
            print(f"   - 历史记录：{PathConfig.HISTORY_DIR}")
            
            return True
            
        except Exception as e:
            print(f"❌ 初始化失败：{str(e)}")
            return False

    def auto_iterative_development(self, improvement_goals=None):
        """自动迭代开发流程"""
        if not self.file_manager:
            print("❌ 请先初始化文件管理器")
            return

        print(f"\n📝 开始处理改进目标：{improvement_goals}")
        self.project_state['user_feedback'].append(improvement_goals)
        
        iteration_count = 0
        max_iterations = self.config['max_iterations']
        min_score = self.config['min_improvement_score']
        
        while iteration_count < max_iterations:
            try:
                print(f"\n🔄 开始第 {iteration_count + 1}/{max_iterations} 次迭代")
                
                # 第一次迭代生成初始代码
                if iteration_count == 0:
                    initial_response = self.call_ai_api(improvement_goals)
                    if initial_response:
                        self.project_state['current_code'] = initial_response
                        self._save_current_version()
                        print("✅ 初始代码生成成功！")
                    else:
                        print("❌ 初始代码生成失败")
                        return False
                
                # 后续迭代进行改进
                else:
                    # 评估当前代码
                    evaluation = self._evaluate_code()
                    if evaluation:
                        score = evaluation['score']
                        print(f"\n📊 当前代码评分：{score:.2f}")
                        
                        # 如果达到目标分数，可以提前结束
                        if score >= min_score:
                            print(f"\n🎯 已达到目标分数 {min_score}，提前完成迭代！")
                            break
                        
                        # 获取改进建议
                        improvements = self._get_improvement_suggestions()
                        if improvements:
                            # 应用改进
                            improved_code = self._apply_improvements(improvements)
                            if improved_code:
                                self.project_state['current_code'] = improved_code
                                self._save_current_version()
                                print("✅ 代码改进成功！")
                            else:
                                print("⚠️ 代码改进失败，保持当前版本")
                        else:
                            print("⚠️ 未获取到改进建议")
                    else:
                        print("⚠️ 代码评估失败")
                
                iteration_count += 1
                
            except Exception as e:
                print(f"\n❌ 迭代过程出错：{str(e)}")
                if iteration_count < max_iterations - 1:
                    print(f"⚠️ 尝试继续下一次迭代...")
                    continue
                else:
                    break
        
        print(f"\n📈 迭代完成统计：")
        print(f"- 总迭代次数: {iteration_count}/{max_iterations}")
        print(f"- 最终版本号: v{self.project_state['version']}")
        
        # 最后一次评估
        final_evaluation = self._evaluate_code()
        if final_evaluation:
            print(f"- 最终代码评分: {final_evaluation['score']:.2f}")
        
        return True

    def _evaluate_code(self):
        """评估代码质量"""
        try:
            # 使用更结构化的评估提示
            prompt = (
                "请对以下代码进行详细评估。评估维度包括：\n"
                "1. 代码结构和组织（架构设计、模块化、职责划分）\n"
                "2. 命名规范和代码风格（PEP8合规性、命名清晰度）\n" 
                "3. 错误处理和异常处理（异常分类、重试机制）\n"
                "4. 代码可读性和注释（文档完整性、注释质量）\n"
                "5. 性能和效率（资源使用、算法优化）\n\n"
                f"代码：\n```python\n{self.project_state['current_code']}\n```\n\n"
                "请严格按照以下格式输出评估结果：\n"
                "{\n"
                '  "scores": {\n'
                '    "structure": 0.85,\n'
                '    "style": 0.80,\n'
                '    "error_handling": 0.75,\n'
                '    "readability": 0.85,\n'
                '    "performance": 0.80\n'
                '  },\n'
                '  "total_score": 0.81,\n'
                '  "analysis": "详细分析内容"\n'
                "}"
            )

            print("\n📊 正在评估代码质量...", flush=True)
            
            response = self.client.chat.completions.create(
                model=self.config['model'],
                messages=[
                    {
                        "role": "system", 
                        "content": (
                            "你是一个严格的代码评估专家。请：\n"
                            "1. 仅输出指定的JSON格式\n"
                            "2. 确保所有分数在0到1之间\n"
                            "3. total_score必须是所有维度的平均值\n"
                            "4. 保持客观公正的评估标准"
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                stream=True
            )

            # 收集完整响应
            evaluation_text = []
            for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    print(content, end='', flush=True)
                    evaluation_text.append(content)

            # 尝试解析JSON
            try:
                full_text = ''.join(evaluation_text)
                # 提取JSON部分
                json_start = full_text.find('{')
                json_end = full_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = full_text[json_start:json_end]
                    evaluation = json.loads(json_str)
                    
                    # 验证评估结果格式
                    if self._validate_evaluation_format(evaluation):
                        return evaluation
                
            except json.JSONDecodeError:
                return self._extract_scores_from_text(''.join(evaluation_text))

        except Exception as e:
            print(f"\n❌ 评估失败：{str(e)}")
            return self._get_default_evaluation()

    def _validate_evaluation_format(self, data: Dict) -> bool:
        """验证评估数据格式"""
        required_keys = {'scores', 'total_score', 'analysis'}
        required_scores = {'structure', 'style', 'error_handling', 'readability', 'performance'}
        
        try:
            # 检查必要键
            if not all(key in data for key in required_keys):
                return False
                
            # 检查分数字典
            scores = data['scores']
            if not all(key in scores for key in required_scores):
                return False
                
            # 验证分数范围
            if not all(0 <= scores[key] <= 1 for key in scores):
                return False
                
            # 验证总分
            total_score = data['total_score']
            if not 0 <= total_score <= 1:
                return False
                
            # 验证分析文本
            if not isinstance(data['analysis'], str) or len(data['analysis']) < 10:
                return False
                
            return True
            
        except Exception:
            return False

    def _extract_scores_from_text(self, text: str) -> dict:
        """从文本中提取评估分数"""
        try:
            scores = {}
            # 使用更灵活的正则表达式匹配分数
            score_patterns = [
                r'([^：\n]+)[:：]\s*(0\.\d+)',  # 中文冒号
                r'([^:\n]+):\s*(0\.\d+)',       # 英文冒号
                r'([^=\n]+)\s*=\s*(0\.\d+)'     # 等号
            ]
            
            for pattern in score_patterns:
                matches = re.finditer(pattern, text)
                for match in matches:
                    key = match.group(1).strip().lower()
                    score = float(match.group(2))
                    
                    # 标准化键名
                    if any(k in key for k in ['结构', 'structure']):
                        scores['structure'] = score
                    elif any(k in key for k in ['风格', 'style']):
                        scores['style'] = score
                    elif any(k in key for k in ['错误', 'error']):
                        scores['error_handling'] = score
                    elif any(k in key for k in ['可读', 'read']):
                        scores['readability'] = score
                    elif any(k in key for k in ['性能', 'performance']):
                        scores['performance'] = score

            if scores:
                # 计算总分
                total_score = sum(scores.values()) / len(scores)
                
                # 提取分析文本
                analysis_patterns = [
                    r'分析[：:](.*?)(?=\n|$)',
                    r'analysis[：:](.*?)(?=\n|$)',
                    r'评估结果[：:](.*?)(?=\n|$)'
                ]
                
                analysis_text = "无详细分析"
                for pattern in analysis_patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        analysis_text = match.group(1).strip()
                        break
                
                return {
                    'scores': scores,
                    'total_score': total_score,
                    'analysis': analysis_text
                }
                
            return self._get_default_evaluation()
            
        except Exception as e:
            print(f"\n⚠️ 分数提取失败：{str(e)}")
            return self._get_default_evaluation()

    def _get_default_evaluation(self) -> dict:
        """获取默认评估结果"""
        return {
            'scores': {
                'structure': 0.5,
                'style': 0.5,
                'error_handling': 0.5,
                'readability': 0.5,
                'performance': 0.5
            },
            'total_score': 0.5,
            'analysis': "无法解析评估结果，使用默认评分。"
        }

    def _get_improvement_suggestions(self):
        """获取代码改进建议"""
        try:
            prompt = (
                "请分析以下代码，提供具体的改进建议。\n"
                "要求：\n"
                "1. 先分析代码的优缺点\n"
                "2. 然后提供具体的改进建议\n"
                "3. 最后给出改进后的完整代码（使用```python和```包裹）\n\n"
                f"当前代码：\n```python\n{self.project_state['current_code']}\n```\n\n"
                "请按以下格式回复：\n"
                "1. 代码分析：\n[分析内容]\n\n"
                "2. 改进建议：\n[具体建议]\n\n"
                "3. 改进后的代码：\n```python\n[完整代码]\n```"
            )
            
            print("\n💡 正在生成改进建议...", flush=True)
            
            response = self.client.chat.completions.create(
                model=self.config['model'],
                messages=[
                    {"role": "system", "content": self.system_prompts['code_improvement']},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                stream=True
            )
            
            # 收集完整响应
            full_response = []
            code_content = []
            in_code_block = False
            
            print("\n🤖 AI反馈：", flush=True)
            
            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    print(content, end='', flush=True)
                    full_response.append(content)
                    
                    # 检测代码块
                    if "```python" in content:
                        in_code_block = True
                        continue
                    elif "```" in content and in_code_block:
                        in_code_block = False
                        continue
                    
                    if in_code_block:
                        code_content.append(content)
            
            # 提取代码内容
            code = ''.join(code_content).strip()
            if not code:
                # 尝试从完整响应中提取代码块
                full_text = ''.join(full_response)
                code_blocks = full_text.split("```python")
                if len(code_blocks) > 1:
                    code = code_blocks[1].split("```")[0].strip()
            
            if not code:
                print("\n⚠️ 未找到有效的代码块")
                return None
            
            print("\n✅ 已生成改进建议")
            return code
            
        except Exception as e:
            print(f"\n❌ 获取改进建议失败：{str(e)}")
            return None

    def _apply_improvements(self, improvements):
        """应用改进建议"""
        if not improvements:
            return None
        
        try:
            # 验证改进后的代码
            if self.validate_code(improvements):
                return improvements
            else:
                print("\n⚠️ 改进后的代码验证失败，尝试重新生成")
                return None
            
        except Exception as e:
            print(f"\n❌ 应用改进失败：{str(e)}")
            return None

    def _save_current_version(self):
        """保存当前版本"""
        if not self.config['auto_save'] or not self.file_manager:
            return

        try:
            if not PathConfig.OUTPUT_DIR:
                raise ValueError("路径配置未初始化")

            version_dir = PathConfig.OUTPUT_DIR / f"v{self.project_state['version']}"
            version_dir.mkdir(exist_ok=True)

            # 保存主代码文件
            main_file = version_dir / "main.py"
            with open(main_file, 'w', encoding='utf-8') as f:
                f.write(self.project_state['current_code'])

            # 更新代码字典
            self.project_state['code'][str(main_file)] = self.project_state['current_code']

            # 保存检查点，包含更多信息
            checkpoint = {
                'version': self.project_state['version'],
                'timestamp': time.time(),
                'files': {
                    str(main_file): {
                        'content': self.project_state['current_code'],
                        'hash': self.file_manager._calculate_file_hash(main_file)
                    }
                },
                'history': self.project_state['history'],
                'user_feedback': self.project_state['user_feedback']
            }

            # 保存检查点文件
            checkpoint_file = version_dir / "checkpoint.json"
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(checkpoint, f, indent=2)
            
            print(f"💾 已保存版本 {self.project_state['version']} 到 {version_dir}")
            
            # 更新版本号
            self.project_state['version'] += 1
            
        except Exception as e:
            print(f"⚠️ 保存失败：{str(e)}")

    def validate_and_merge_code(self, new_code):
        """验证并合并代码"""
        if self.validate_code(new_code):
            self.project_state['history'].append(self.project_state['current_code'])
            self.project_state['current_code'] = new_code
            self.project_state['version'] += 1
            return True
        return False

    def should_continue_iteration(self):
        """评估是否需要继续迭代（使用流式输出）"""
        try:
            prompt = (
                "请评估以下代码是否还需要进一步改进：\n\n"
                f"{self.project_state['current_code']}\n\n"
                "如果代码已经完善，请回复'DONE'，否则请简要说明需要改进的地方。"
            )
            
            print("\n🔍 正在评估代码...", flush=True)
            
            response = self.client.chat.completions.create(
                model=self.config['model'],
                messages=[
                    {"role": "system", "content": self.system_prompts['code_review']},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=100,
                stream=self.config['stream']
            )
            
            if self.config['stream']:
                feedback = self._stream_output(response)
            else:
                feedback = response.choices[0].message.content
            
            self.config['current_api_calls'] += 1
            
            if feedback.upper().strip() == 'DONE':
                return False
                
            self.project_state['user_feedback'].append(feedback)
            return True
            
        except Exception as e:
            print(f"❌ 评估失败：{str(e)}")
            return False

    def _update_project_state(self, modified_files: Dict[str, str]):
        """更新项目状态"""
        for file_path, status in modified_files.items():
            if status == 'deleted':
                # 从项目状态中移除已删除的文件
                if file_path in self.project_state['code']:
                    del self.project_state['code'][file_path]
            else:
                # 更新修改的文件内容
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        self.project_state['code'][file_path] = f.read()
                except Exception as e:
                    print(f"⚠️ 更新文件失败 {file_path}: {e}")

    def validate_code(self, code: str) -> bool:
        """增强的代码验证"""
        if not code or not isinstance(code, str):
            print("⚠️ 无效的代码内容")
            return False
        
        try:
            # 移除代码块标记
            code = code.strip()
            if code.startswith("```python"):
                code = code[8:]
            if code.endswith("```"):
                code = code[:-3]
            code = code.strip()
            
            # 基本验证
            if len(code.strip().split('\n')) < 10:
                print("⚠️ 代码内容不完整")
                return False
                
            # 检查必要组件
            required_components = [
                'import', 'class', 'def', '"""', 'try:', 'except'
            ]
            missing = [comp for comp in required_components if comp not in code]
            if missing:
                print(f"⚠️ 缺少必要组件: {', '.join(missing)}")
                return False
            
            # 语法检查
            compile(code, '<string>', 'exec')
            
            # 安全检查
            dangerous_imports = ['subprocess', 'os.system', 'eval', 'exec']
            for imp in dangerous_imports:
                if imp in code:
                    print(f"⚠️ 发现潜在危险导入/调用: {imp}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"❌ 代码验证失败：{str(e)}")
            return False

    def load_existing_project(self, project_dir: str) -> bool:
        """加载现有项目进行迭代"""
        try:
            project_path = Path(project_dir)
            if not project_path.exists():
                print(f"❌ 项目目录不存在：{project_dir}")
                return False
            
            # 初始化文件管理器
            if not self.init_file_manager(project_dir):
                return False
            
            # 查找最新版本
            versions = sorted([
                d for d in project_path.iterdir() 
                if d.is_dir() and d.name.startswith('v')
            ], key=lambda x: int(x.name[1:]))
            
            if not versions:
                print("❌ 未找到任何版本")
                return False
            
            latest_version = versions[-1]
            main_file = latest_version / "main.py"
            
            if not main_file.exists():
                print(f"❌ 未找到主文件：{main_file}")
                return False
            
            # 读取最新版本的代码
            with open(main_file, 'r', encoding='utf-8') as f:
                current_code = f.read()
            
            # 读取检查点信息
            checkpoint_file = latest_version / "checkpoint.json"
            if checkpoint_file.exists():
                with open(checkpoint_file, 'r', encoding='utf-8') as f:
                    checkpoint = json.load(f)
                    version = checkpoint.get('version', int(latest_version.name[1:]))
                    # 读取历史记录
                    self.project_state['history'] = checkpoint.get('history', [])
                    self.project_state['user_feedback'] = checkpoint.get('user_feedback', [])
            else:
                version = int(latest_version.name[1:])
            
            # 更新项目状态
            self.project_state.update({
                'current_code': current_code,
                'version': version + 1,  # 设置为下一个版本
                'code': {str(main_file): current_code}
            })
            
            print(f"\n✅ 已加载项目：{project_dir}")
            print(f"📄 当前版本：v{version}")
            print("\n📝 当前代码概要：")
            self._print_code_summary(current_code)
            return True
            
        except Exception as e:
            print(f"❌ 加载项目失败：{str(e)}")
            return False

    def _print_code_summary(self, code: str):
        """打印代码概要信息"""
        try:
            lines = code.split('\n')
            total_lines = len(lines)
            
            # 提取文档字符串
            doc_string = ""
            if '"""' in lines[0]:
                for i, line in enumerate(lines[1:], 1):
                    if '"""' in line:
                        doc_string = '\n'.join(lines[1:i])
                        break
            
            # 提取类和函数定义
            classes = []
            functions = []
            for line in lines:
                line = line.strip()
                if line.startswith('class '):
                    classes.append(line.split('(')[0].replace('class ', ''))
                elif line.startswith('def '):
                    functions.append(line.split('(')[0].replace('def ', ''))
            
            # 打印概要
            print(f"\n总行数：{total_lines}")
            if doc_string:
                print(f"\n文档描述：\n{doc_string.strip()}")
            if classes:
                print(f"\n包含的类：\n- " + "\n- ".join(classes))
            if functions:
                print(f"\n包含的函数：\n- " + "\n- ".join(functions))
            
        except Exception as e:
            print(f"⚠️ 无法解析代码概要：{str(e)}")

    def continue_iteration(self, improvement_goals: str = None) -> bool:
        """继续迭代现有项目"""
        if not self.project_state.get('current_code'):
            print("❌ 没有可迭代的代码，请先加载项目")
            return False
        
        if not improvement_goals:
            print("\n💡 请选择改进方向：")
            print("1. 代码优化和重构")
            print("2. 功能扩展和增强")
            print("3. 性能改进")
            print("4. 错误处理完善")
            print("5. 文档和注释补充")
            print("6. 自定义改进目标")
            
            choice = input("\n请选择 (1-6): ").strip()
            
            goals_map = {
                '1': "优化代码结构，提高可读性和可维护性",
                '2': "扩展现有功能，添加新特性",
                '3': "改进代码性能，优化资源使用",
                '4': "完善错误处理，提高代码健壮性",
                '5': "补充文档和注释，提高代码可理解性"
            }
            
            if choice in goals_map:
                improvement_goals = goals_map[choice]
            elif choice == '6':
                improvement_goals = input("\n请输入具体的改进目标：").strip()
            else:
                print("❌ 无效的选择")
                return False
        
        # 构建包含现有代码的改进提示
        prompt = f"""基于以下现有代码进行改进：

{self.project_state['current_code']}

改进目标：{improvement_goals}

请保持代码的核心功能，在此基础上进行改进。
"""
        
        print(f"\n🎯 改进目标：{improvement_goals}")
        return self.auto_iterative_development(prompt)

    async def _process_evaluation_stream(self, response) -> Dict:
        """处理评估流式响应"""
        full_response = []
        buffer = ""
        
        try:
            async for chunk in response:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    print(content, end='', flush=True)
                    buffer += content
                    
                    # 当遇到完整的JSON时解析
                    if buffer.count('{') == buffer.count('}') and '{' in buffer:
                        try:
                            evaluation = json.loads(buffer)
                            if self._validate_evaluation_format(evaluation):
                                return evaluation
                        except json.JSONDecodeError:
                            continue
                            
            # 完整响应解析
            full_text = ''.join(full_response)
            try:
                # 尝试提取JSON部分
                json_start = full_text.find('{')
                json_end = full_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    json_str = full_text[json_start:json_end]
                    evaluation = json.loads(json_str)
                    if self._validate_evaluation_format(evaluation):
                        return evaluation
            except json.JSONDecodeError:
                pass
                
            # 如果JSON解析失败，使用正则提取分数
            return self._extract_scores_from_text(full_text)
            
        except Exception as e:
            print(f"\n❌ 评估处理失败：{str(e)}")
            return self._get_default_evaluation()

def get_project_source():
    """获取项目来源"""
    options = {
        "1": "创建新项目",
        "2": "迭代现有项目"
    }
    
    print("\n请选择项目来源：")
    for key, desc in options.items():
        print(f"{key}. {desc}")
    
    while True:
        choice = input("\n请选择 (1-2): ").strip()
        if choice in options:
            return choice
        print("❌ 无效的选择，请重试")

if __name__ == "__main__":
    # 初始化配置
    API_KEY = "_yV91xd1MYtZvKbOl2NLWfZh8PR_tJfIBnJ9j7ZZbFQ"
    
    print("🚀 AI代码生成器启动")
    print("=" * 50)
    
    # 设置项目根目录
    project_root = input("\n📂 请输入项目根目录路径: ").strip()
    if not os.path.exists(project_root):
        print("❌ 目录不存在")
        exit(1)
    
    # 创建开发实例
    developer = AIIterativeDeveloper(
        API_KEY, 
        ""
    )
    
    # 选择项目来源
    source_choice = get_project_source()
    
    if source_choice == "1":  # 创建新项目
        # 初始化文件管理器
        developer.init_file_manager(project_root)
        
        print("\n💡 项目类型示例：")
        print("1. 命令行工具")
        print("2. 简单游戏")
        print("3. 数据处理")
        print("4. Web应用")
        print("5. 自动化脚本")
        
        # 设置迭代参数
        developer.config.update({
            'max_iterations': int(input("\n🔄 请输入最大迭代次数 (默认5): ") or "5"),
            'min_improvement_score': float(input("📊 请输入最小改进分数 (0-1，默认0.7): ") or "0.7"),
            'auto_save': input("💾 是否自动保存每次迭代 (y/n，默认y): ").lower() != 'n'
        })
        
        # 开始自动迭代
        improvement_goals = input("\n💡 请输入项目需求（请详细描述您想要的Python项目）：").strip()
        if not improvement_goals:
            print("❌ 请输入项目需求")
            exit(1)
            
        developer.auto_iterative_development(improvement_goals)
        
    else:  # 迭代现有项目
        if developer.load_existing_project(project_root):
            # 设置迭代参数
            developer.config.update({
                'max_iterations': int(input("\n🔄 请输入最大迭代次数 (默认3): ") or "3"),
                'min_improvement_score': float(input("📊 请输入最小改进分数 (0-1，默认0.7): ") or "0.7"),
                'auto_save': input("💾 是否自动保存每次迭代 (y/n，默认y): ").lower() != 'n'
            })
            
            # 继续迭代
            developer.continue_iteration()
        else:
            print("❌ 加载项目失败")
            exit(1)
    
    print("\n🎉 处理完成！") 