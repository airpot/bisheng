from bisheng_langchain.chat_models import ChatQWen
from langchain_community.chat_models import ChatOpenAI
from typing import List
import logging

logger = logging.getLogger(__name__)

# 添加生成标签功能
def generate_tags(content: str, model_name: str = "qwen-plus", max_tags: int = 5) -> List[str]:
    """使用大模型生成文档标签"""
    prompt = f"""
根据以下文档内容生成{max_tags}个最相关的标签，用逗号分隔：

{content[:2000]}  # 限制输入长度

要求：
1. 返回最相关的{max_tags}个标签
2. 标签应简洁明了
3. 用中文标签
4. 用逗号分隔
"""
    
    try:
        # 根据模型名称选择合适的模型
        if model_name.startswith("qwen"):
            llm = ChatQWen(model=model_name, temperature=0.3, max_tokens=100)
        else:
            # 默认使用OpenAI模型
            llm = ChatOpenAI(model_name=model_name, temperature=0.3, max_tokens=100)
        
        # 调用模型生成标签
        response = llm.invoke(prompt)
        
        # 解析响应
        tags_text = response.content if hasattr(response, 'content') else str(response)
        tags = tags_text.strip().split(',')
        # 清理标签
        tags = [tag.strip() for tag in tags if tag.strip()]
        return tags[:max_tags]
    except Exception as e:
        logger.error(f"Failed to generate tags: {str(e)}")
        return []
