import os
import random
import re
import asyncio
from datetime import datetime
from collections import deque
from typing import Dict, List, Deque
from nicegui import ui
from openai import AsyncOpenAI, APIError, APITimeoutError
from tenacity import retry, stop_after_attempt, wait_random_exponential, retry_if_exception_type

class FantasyDialogueGenerator:
    """
    增强版玄幻小说对话生成器
    新增功能：多分隔符支持、模板引擎优化、API重试机制、实时输入校验
    """
    MAX_HISTORY = 10
    MODEL_CONFIG = {
        'model': 'gpt-3.5-turbo',
        'temperature': 0.75,
        'max_tokens': 600,
        'timeout': 15
    }
    ROLE_SEPARATORS = re.compile(r'[与和及、]+')
    STYLE_CLASSES = {
        'header': 'bg-gradient-to-r from-blue-800 to-purple-800 p-4 shadow-lg',
        'title': 'text-3xl font-bold text-white text-center',
        'input_container': 'w-full max-w-5xl mx-auto p-4 lg:p-6',
        'input_column': 'w-full lg:w-1/3 space-y-4',
        'output_column': 'w-full lg:w-2/3 space-y-4 mt-6 lg:mt-0',
        'history_card': 'w-full p-4 bg-white rounded-lg shadow-sm hover:shadow-md transition-shadow'
    }

    def __init__(self):
        self.history: Deque[Dict] = deque(maxlen=self.MAX_HISTORY)
        self.client = self._init_openai_client()
        self._setup_observers()
        self.setup_ui()

    def _init_openai_client(self):
        """初始化异步OpenAI客户端"""
        if api_key := os.getenv('OPENAI_API_KEY'):
            return AsyncOpenAI(api_key=api_key)
        return None

    def _setup_observers(self):
        """设置输入实时校验"""
        self._last_valid_roles = []
        self._last_valid_context = ''

    def setup_ui(self) -> None:
        """增强响应式UI布局"""
        with ui.header().classes(self.STYLE_CLASSES['header']):
            ui.label('🎭 玄幻小说对话生成器').classes(self.STYLE_CLASSES['title'])
            
        with ui.row().classes(self.STYLE_CLASSES['input_container']):
            with ui.column().classes(self.STYLE_CLASSES['input_column']):
                # 角色输入增强
                with ui.input('角色设定（2-4个角色）', placeholder='示例：仙尊 与 魔道圣女').classes('w-full') as self.role_input:
                    ui.tooltip('支持分隔符：与、和、及、顿号').classes('text-sm')
                    ui.badge('', color='red').bind_text_from(self, 'role_status').classes('ml-2')
                self.role_input.validation = {'分隔符': lambda v: len(self._parse_roles(v)) >= 2}
                self.role_status = ''

                # 情境输入增强
                with ui.textarea('情境设定').classes('w-full h-40') as self.context_input:
                    with ui.row().classes('w-full justify-between items-center text-sm'):
                        ui.badge('0/500', color='blue').bind_text_from(
                            self.context_input, 'value', 
                            backward=lambda v: f"{len(v)}/500"
                        )
                        ui.badge('', color='red').bind_text_from(self, 'context_status')
                self.context_input.validation = {'必填': lambda v: bool(v.strip())}
                self.context_status = ''

                # 生成按钮增强
                self.generate_btn = ui.button('生成对话', on_click=self.generate_dialogue).classes('w-full')
                ui.linear_progress(0).bind_visibility_from(self, 'loading').props('instant-feedback')

            with ui.column().classes(self.STYLE_CLASSES['output_column']):
                self.dialogue_output = ui.markdown().classes('p-4 bg-gray-50 rounded-lg min-h-48')
                self.error_display = ui.label().classes('text-red-500 italic')
                
                # 增强历史记录
                with ui.expansion('历史记录', icon='history').classes('w-full'):
                    self.history_container = ui.column().classes('space-y-4')

    def _parse_roles(self, value: str) -> List[str]:
        """解析多种分隔符的角色设定"""
        return [r.strip() for r in self.ROLE_SEPARATORS.split(value) if r.strip()]

    async def generate_dialogue(self) -> None:
        """增强生成逻辑"""
        try:
            self._validate_inputs()
            self._set_loading(True)
            
            prompt = self._build_system_prompt()
            response = await self._call_llm_with_retry(prompt)
            
            self._add_history(response)
            self._show_output(response)
            
        except Exception as e:
            self._handle_error(e)
        finally:
            self._set_loading(False)

    def _validate_inputs(self) -> None:
        """增强实时校验逻辑"""
        roles = self._parse_roles(self.role_input.value)
        context = self.context_input.value.strip()
        
        if len(roles) < 2:
            raise ValueError('至少需要2个角色')
        if len(roles) > 4:
            raise ValueError('最多支持4个角色')
        if not context:
            raise ValueError('情境设定不能为空')
        if len(context) > 500:
            raise ValueError('情境设定超过500字')

    def _build_system_prompt(self) -> str:
        """构建带示例的系统提示词"""
        roles = self._parse_roles(self.role_input.value)
        example = """
        【示例格式】
        凌渊仙尊：「此阵乃上古传承，尔等岂能妄破！」
        赤焰魔君（周身煞气翻涌）：「哈哈哈，本座偏要逆天而行！」（挥动万魂幡）
        清瑶仙子：素手结印，九霄环佩发出清鸣：「道友速退，此阵凶险异常！」
        """
        return f"""
        你是一位资深玄幻小说作家，请根据以下设定生成对话：
        - 角色：{", ".join(roles)}
        - 情境：{self.context_input.value}
        
        要求：
        1. 5-7轮对话，保持节奏紧凑
        2. 合理分配角色台词，避免单角色独白
        3. 使用玄幻特有词汇（如：真元、结印、法宝）
        4. 对话格式：角色名（可选动作）：「内容」
        5. 适当添加场景描写（用括号标注）
        
        {example}
        """

    @retry(stop=stop_after_attempt(3),
           wait=wait_random_exponential(multiplier=1, max=10),
           retry=retry_if_exception_type((APIError, APITimeoutError)))
    async def _call_llm_with_retry(self, prompt: str) -> str:
        """带重试机制的API调用"""
        try:
            if self.client:
                response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        messages=[{
                            "role": "system",
                            "content": "你是一位精通中国玄幻小说创作的作家",
                        }, {
                            "role": "user", 
                            "content": prompt
                        }],
                        **self.MODEL_CONFIG
                    ),
                    timeout=self.MODEL_CONFIG['timeout']
                )
                return response.choices[0].message.content
            return self._generate_enhanced_sample()
        except APITimeoutError:
            return "请求超时，已启用模拟对话..."

    def _generate_enhanced_sample(self) -> str:
        """多角色模拟对话生成"""
        roles = self._parse_roles(self.role_input.value)
        templates = [
            lambda c: f"{c}「{random.choice(['哼，雕虫小技！','尔等竟敢！','天地无极，乾坤借法！'])}」",
            lambda c: f"{c}（{random.choice(['剑指苍穹','祭出法宝','吐出一口精血'])}）「{random.choice(['看招！','破！','道友小心！'])}」"
        ]
        return '\n\n'.join(
            f"{random.choice(templates)(role)}" 
            for _ in range(random.randint(5,7)) 
            for role in random.sample(roles, k=2)
        )

    def _add_history(self, content: str) -> None:
        """增量更新历史记录"""
        record = {
            'time': datetime.now().strftime('%H:%M'),
            'roles': self._parse_roles(self.role_input.value),
            'context': self.context_input.value,
            'content': content
        }
        self.history.appendleft(record)
        
        # 仅添加新条目
        with self.history_container:
            with ui.card().classes(self.STYLE_CLASSES['history_card']):
                ui.label(f"⏰ {record['time']} | 角色：{'、'.join(record['roles'])}").classes('text-sm')
                ui.markdown(f"**情境**：{record['context'][:35]}...").classes('text-gray-600')
                ui.separator().classes('my-2')
                ui.markdown(record['content']).classes('text-sm')
                ui.button(icon='content_copy', on_click=lambda: ui.notify('已复制')).props('dense flat')

    def _show_output(self, content: str) -> None:
        """显示输出并滚动到结果"""
        self.dialogue_output.content = content
        self.error_display.text = None
        ui.run_javascript('window.scrollTo(0, document.documentElement.scrollHeight || document.body.scrollHeight);')

    def _set_loading(self, state: bool) -> None:
        """优化加载状态管理"""
        self.loading = state
        self.generate_btn.disable = state
        ui.update()

    def _handle_error(self, error: Exception) -> None:
        """增强错误处理"""
        error_msg = {
            ValueError: lambda e: f"输入错误：{str(e)}",
            APIError: lambda e: f"API错误：{e.message.split('(')[0]}",
            APITimeoutError: lambda _: "请求超时，请稍后重试"
        }.get(type(error), lambda e: f"系统错误：{str(e)}")(error)
        
        self.error_display.text = error_msg
        ui.notify(error_msg, type='negative', position='top-right')

if __name__ == "__main__":
    app = FantasyDialogueGenerator()
    ui.run(
        title="玄幻对话生成器",
        reload=False,
        port=8080,
        favicon="⚔️",
        dark=True,
        tailwind=True
    )