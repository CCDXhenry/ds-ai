import os
import random
import asyncio
from collections import deque
from typing import Dict, List, Tuple, Optional, Deque
from nicegui import ui
from openai import OpenAI, APIError

class FantasyDialogueGenerator:
    """
    玄幻小说对话生成器核心类
    
    配置参数：
    - MAX_HISTORY: 最大历史记录数
    - MODEL_CONFIG: OpenAI模型配置
    - STYLE_CLASSES: UI样式类配置
    - SAMPLE_TEMPLATES: 模拟对话模板
    """
    MAX_HISTORY = 10
    MODEL_CONFIG = {
        'model': 'gpt-3.5-turbo',
        'temperature': 0.7,
        'max_tokens': 500
    }
    STYLE_CLASSES = {
        'header': 'bg-blue-100 p-4',
        'title': 'text-2xl font-bold text-blue-800',
        'input_container': 'w-full max-w-3xl mx-auto p-6',
        'input_column': 'w-1/3 space-y-4',
        'output_column': 'w-2/3 space-y-4',
        'history_card': 'w-full p-4 bg-white shadow-sm'
    }
    SAMPLE_TEMPLATES = [
        "{c1}：「{content}」\n{c2}：（{action}）「{reply}」",
        "{c1}（冷然）：「{content}」\n{c2}微微眯眼：「{reply}」",
        "{c1}结印喝道：「{content}」\n{c2}掌中{object}光芒大盛：「{reply}」"
    ]

    def __init__(self):
        self.history: Deque[Dict[str, str]] = deque(maxlen=self.MAX_HISTORY)
        self.client = self._init_openai_client()
        self.setup_ui()

    def _init_openai_client(self):
        """初始化OpenAI客户端"""
        if api_key := os.getenv('OPENAI_API_KEY'):
            return OpenAI(api_key=api_key)
        return None

    def setup_ui(self) -> None:
        """初始化用户界面组件"""
        with ui.header().classes(self.STYLE_CLASSES['header']):
            ui.label('玄幻小说对话生成器').classes(self.STYLE_CLASSES['title'])
            
        with ui.row().classes(self.STYLE_CLASSES['input_container']):
            # 输入区域
            with ui.column().classes(self.STYLE_CLASSES['input_column']):
                self.role_input = ui.input('角色设定（2-4个角色，用"与"分隔）',
                                         placeholder='示例：仙尊与魔道圣女').classes('w-full')
                self.context_input = ui.textarea('情境设定（50字以内）',
                                               placeholder='示例：在九幽秘境争夺上古神器').classes('w-full h-32')
                self.generate_btn = ui.button('生成对话', on_click=self.generate_dialogue).classes('w-full')
                
            # 输出区域
            with ui.column().classes(self.STYLE_CLASSES['output_column']):
                self.loading = ui.spinner(size='lg', color='blue').bind_visibility_from(self, 'loading')
                self.dialogue_output = ui.markdown().classes('p-4 bg-gray-50 rounded-lg min-h-48')
                self.error_message = ui.label().classes('text-red-500').bind_visibility_from(self, 'error_message')
                
                # 历史记录
                ui.label('最近生成').classes('text-xl font-semibold mt-4')
                self.history_container = ui.column().classes('space-y-4')

    async def generate_dialogue(self) -> None:
        """生成对话的核心逻辑"""
        try:
            self._validate_inputs()
            self._set_loading_state(True)
            
            prompt = self._build_prompt()
            response = await self._call_llm(prompt)
            
            self._add_to_history(response)
            self._update_display(response)
            
        except ValueError as ve:
            self.error_message = f"输入错误: {str(ve)}"
        except APIError as api_err:
            self.error_message = f"接口请求失败: {api_err.message.split('(')[0]}"
        except Exception as e:
            self.error_message = f"系统错误: {str(e)}"
        finally:
            self._set_loading_state(False)

    def _validate_inputs(self) -> None:
        """增强输入验证"""
        role = self.role_input.value.strip()
        context = self.context_input.value.strip()
        
        if not role:
            raise ValueError("必须填写角色设定")
        if '与' not in role or len(role.split('与')) < 2:
            raise ValueError("角色设定需包含至少两个角色，用'与'分隔")
        if len(role) > 100:
            raise ValueError("角色设定不得超过100字")
        if not context:
            raise ValueError("必须填写情境设定")
        if len(context) > 500:
            raise ValueError("情境设定不得超过500字")

    def _build_prompt(self) -> str:
        """构建LLM提示词"""
        return f"""
        请生成一段符合中国玄幻小说风格的对话。要求：
        1. 角色：{self.role_input.value}
        2. 情境：{self.context_input.value}
        3. 包含5-7轮自然对话
        4. 使用恰当的文言文与现代汉语结合的表达方式
        5. 每段对话前用角色名称标注，格式示例：
           角色A：「对话内容」
           角色B：（动作描写）「对话内容」
        """

    async def _call_llm(self, prompt: str) -> str:
        """调用大语言模型生成内容"""
        if self.client:
            response = self.client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                **self.MODEL_CONFIG
            )
            return response.choices[0].message.content
        else:
            await asyncio.sleep(1)  # 模拟网络延迟
            return self._generate_sample_dialogue()

    def _generate_sample_dialogue(self) -> str:
        """增强模拟对话生成"""
        characters = self.role_input.value.split('与')
        if len(characters) < 2:
            characters = ['仙尊', '魔尊']
            
        template = random.choice(self.SAMPLE_TEMPLATES)
        elements = {
            'c1': characters[0].strip(),
            'c2': characters[1].strip(),
            'content': random.choice(['此物乃我宗门至宝', '阁下未免太过狂妄', '天地灵物岂容尔等玷污']),
            'action': random.choice(['冷笑', '拂袖', '剑指虚空']),
            'reply': random.choice(['有能者居之', '今日便要踏平此山', '且看你能奈我何']),
            'object': random.choice(['法宝', '灵剑', '符咒'])
        }
        return template.format(**elements).replace('\n', '\n\n')

    def _add_to_history(self, content: str) -> None:
        """添加记录到历史"""
        self.history.appendleft({
            'role': self.role_input.value,
            'context': self.context_input.value,
            'content': content
        })
        self._update_history_display()

    def _update_history_display(self) -> None:
        """优化历史记录显示"""
        self.history_container.clear()
        for item in self.history:
            with ui.card().classes(self.STYLE_CLASSES['history_card']):
                ui.label(f"角色：{item['role']}").classes('font-medium')
                ui.label(f"情境：{item['context'][:30]}...").classes('text-sm text-gray-600')
                ui.markdown(item['content']).classes('mt-2')

    def _update_display(self, content: str) -> None:
        """更新主显示区域"""
        self.dialogue_output.content = content
        self.error_message = None

    def _set_loading_state(self, state: bool) -> None:
        """控制加载状态"""
        self.generate_btn.disable = state
        self.loading.visible = state

if __name__ in {"__main__", "__mp_main__"}:
    app = FantasyDialogueGenerator()
    ui.run(
        title="玄幻对话生成器",
        reload=False,
        port=8080,
        favicon="✨",
        dark=False
    )