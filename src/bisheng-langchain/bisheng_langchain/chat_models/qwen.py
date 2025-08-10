"""proxy llm chat wrapper."""
from __future__ import annotations

import copy
import json
import logging
import sys
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

import dashscope
from dashscope import Generation
from pydantic import Field, validator

from bisheng_langchain.utils.requests import Requests
from bisheng_langchain.utils import _import_tiktoken
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (AIMessage, BaseMessage, ChatMessage, FunctionMessage,
                                     HumanMessage, SystemMessage, ToolMessage)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.pydantic_v1 import Field, validator
from langchain_core.utils import get_from_dict_or_env
from requests.adapters import HTTPAdapter
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential
from urllib3.util.retry import Retry

DASHSCOPE_AVAILABLE = True
try:
    import dashscope
    from dashscope import Generation
except ImportError:
    DASHSCOPE_AVAILABLE = False

if TYPE_CHECKING:
    import tiktoken

logger = logging.getLogger(__name__)


def _import_tiktoken() -> Any:
    try:
        import tiktoken
    except ImportError:
        raise ValueError('Could not import tiktoken python package. '
                         'This is needed in order to calculate get_token_ids. '
                         'Please install it with `pip install tiktoken`.')
    return tiktoken


def _create_retry_decorator(llm: ChatQWen) -> Callable[[Any], Any]:

    min_seconds = 1
    max_seconds = 20
    # Wait 2^x * 1 second between each retry starting with
    # 4 seconds, then up to 10 seconds, then 10 seconds afterwards
    return retry(
        reraise=True,
        stop=stop_after_attempt(llm.max_retries),
        wait=wait_exponential(multiplier=1, min=min_seconds, max=max_seconds),
        retry=(retry_if_exception_type(Exception)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )


def _convert_message_to_dict(message: BaseMessage) -> dict:
    if isinstance(message, ChatMessage):
        message_dict = {'role': message.role, 'content': message.content}
    elif isinstance(message, HumanMessage):
        message_dict = {'role': 'user', 'content': message.content}
    elif isinstance(message, AIMessage):
        message_dict = {'role': 'assistant', 'content': message.content}
        if 'function_call' in message.additional_kwargs:
            message_dict['function_call'] = message.additional_kwargs['function_call']
        if "tool_calls" in message.additional_kwargs:
            message_dict["tool_calls"] = message.additional_kwargs["tool_calls"]
    elif isinstance(message, SystemMessage):
        message_dict = {'role': 'system', 'content': message.content}
    elif isinstance(message, FunctionMessage):
        message_dict = {
            'role': 'function',
            'content': message.content,
            'name': message.name,
        }
    elif isinstance(message, ToolMessage):
        message_dict = {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }
    else:
        raise ValueError(f'Got unknown type {message}')
    if 'name' in message.additional_kwargs:
        message_dict['name'] = message.additional_kwargs['name']
    return message_dict


def _convert_dict_to_message(_dict: Mapping[str, Any]) -> BaseMessage:
    role = _dict['role']
    if role == 'user':
        return HumanMessage(content=_dict['content'])
    elif role == 'assistant':
        content = _dict['content'] or ''
        additional_kwargs = {}
        if 'function_call' in _dict:
            additional_kwargs['function_call'] = dict(_dict['function_call'])
        if 'tool_calls' in _dict:
            additional_kwargs['tool_calls'] = _dict['tool_calls']
        return AIMessage(content=content, additional_kwargs=additional_kwargs)
    elif role == 'system':
        return SystemMessage(content=_dict['content'])
    elif role == 'function':
        return FunctionMessage(content=_dict['content'], name=_dict['name'])
    elif role == 'tool':
        return ToolMessage(content=_dict['content'], tool_call_id=_dict['tool_call_id'])
    else:
        return ChatMessage(content=_dict['content'], role=role)


url = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'


class ChatQWen(BaseChatModel):
    """Wrapper around proxy Chat large language models.

    To use, the environment variable ``api_key`` set with your API key.

    Example:
        .. code-block:: python

            from bisheng_langchain.chat_models import ChatQWen
            chat_qwen = ChatQWen(model_name="qwen-turbo")
    """

    client: Optional[Any] = None  #: :meta private:
    """Model name to use."""
    model_name: str = Field('qwen-turbo', alias='model')

    temperature: float = 0.95
    top_p: float = 0.8
    repetition_penalty: float = 1.1
    top_k: int = None
    seed: Optional[int] = 1234
    """生成时，随机数的种子，用于控制模型生成的随机性。如果使用相同的种子，每次运行生成的结果都将相同；"""
    """What sampling temperature to use."""
    model_kwargs: Optional[Dict[str, Any]] = Field(default_factory=dict)
    """Holds any model parameters valid for `create` call not explicitly specified."""
    dashscope_api_key: Optional[str] = None

    request_timeout: Optional[Union[float, Tuple[float, float]]] = None
    """Timeout for requests to OpenAI completion API. Default is 600 seconds."""
    max_retries: Optional[int] = 3
    """Maximum number of retries to make when generating."""
    streaming: Optional[bool] = False
    """Whether to stream the results or not."""
    max_tokens: Optional[int] = 1024
    """Maximum number of tokens to generate."""
    result_format: Optional[str] = 'message'
    """compatibale with openai"""
    tiktoken_model_name: Optional[str] = None
    """The model name to pass to tiktoken when using this class.
    Tiktoken is used to count the number of tokens in documents to constrain
    them to be under a certain limit. By default, when set to None, this will
    be the same as the embedding model name. However, there are some cases
    where you may want to use this Embedding class with a model name not
    supported by tiktoken. This can include when using Azure embeddings or
    when using one of the many model providers that expose an OpenAI-like
    API but with different models. In those cases, in order to avoid erroring
    when tiktoken is called, you can specify a model name to use here."""
    verbose: Optional[bool] = False
    use_dashscope_sdk: Optional[bool] = True
    """Whether to use the official DashScope SDK or the custom implementation."""

    class Config:
        """Configuration for this pydantic object."""

        allow_population_by_field_name = True

    @validator('use_dashscope_sdk')
    def validate_use_dashscope_sdk(cls, use_dashscope_sdk, values):
        """Validate that the use_dashscope_sdk is only True when the dashscope package is available."""
        if use_dashscope_sdk and not DASHSCOPE_AVAILABLE:
            raise ValueError(
                "The `dashscope` package is not installed. "
                "Please install it via `pip install dashscope` to use the official SDK."
            )
        return use_dashscope_sdk

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the DashScope API client."""
        super().__init__(**kwargs)
        self.dashscope_api_key = get_from_dict_or_env(
            kwargs, 'dashscope_api_key', 'DASHSCOPE_API_KEY'
        )

        if self.use_dashscope_sdk:
            # Use the official DashScope SDK
            dashscope.api_key = self.dashscope_api_key
        else:
            # Use the custom implementation
            try:
                header = {
                    'Authorization': f'Bearer {self.dashscope_api_key}',
                    'Content-Type': 'application/json'
                }
                self.client = Requests(headers=header, )
            except AttributeError:
                raise ValueError(
                    'Try upgrading it with `pip install --upgrade requests`.'
                )

    @property
    def _default_params(self) -> Dict[str, Any]:
        """Get the default parameters for calling ChatWenxin API."""
        return {
            'temperature': self.temperature,
            'top_p': self.top_p,
            'top_k': self.top_k,
            'max_tokens': self.max_tokens,
            'seed': self.seed,
            'result_format': self.result_format,
            'repetition_penalty': self.repetition_penalty,
            **self.model_kwargs,
        }

    def completion_with_retry(self, **kwargs: Any) -> Any:
        retry_decorator = _create_retry_decorator(self)
        self.client.headers.pop('Accept', '')

        @retry_decorator
        def _completion_with_retry(**kwargs: Any) -> Any:
            messages = kwargs.pop('messages', '')
            input, params = ChatQWen._build_input_parameters(self.model_name,
                                                             messages=messages,
                                                             **kwargs)
            inp = {'input': input, 'parameters': params, 'model': self.model_name}
            return self.client.post(url=url, json=inp).json()

        rsp_dict = _completion_with_retry(**kwargs)
        if 'code' in rsp_dict and rsp_dict['code'] == 'DataInspectionFailed':
            output_res = {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': rsp_dict['message']}}]} 
            usage_res = {'total_tokens': 2, 'output_tokens': 1, 'input_tokens': 1}
            return output_res, usage_res
        elif 'output' not in rsp_dict:
            logger.error(f'proxy_llm_error resp={rsp_dict}')
            message = rsp_dict['message']
            raise Exception(message)
        else:
            return rsp_dict['output'], rsp_dict.get('usage', '')


    def _combine_llm_outputs(self, llm_outputs: List[Optional[dict]]) -> dict:
        overall_token_usage: dict = {}
        for output in llm_outputs:
            if output is None:
                # Happens in streaming
                continue
            token_usage = output['token_usage']
            for k, v in token_usage.items():
                if k in overall_token_usage:
                    overall_token_usage[k] += v
                else:
                    overall_token_usage[k] = v
        return {'token_usage': overall_token_usage, 'model_name': self.model_name}

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate a chat response."""
        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {**params, **kwargs}

        if self.use_dashscope_sdk:
            return self._generate_with_sdk(message_dicts, params, run_manager)
        else:
            output, usage = self.completion_with_retry(messages=message_dicts, **params)
            return self._create_chat_result(output, usage)

    def _generate_with_sdk(
        self,
        messages: List[Dict[str, Any]],
        params: Dict[str, Any],
        run_manager: Optional[CallbackManagerForLLMRun] = None,
    ) -> ChatResult:
        """Generate a chat response using the official DashScope SDK."""
        # Prepare the parameters
        parameters = {
            "temperature": params.get("temperature", self.temperature),
            "top_p": params.get("top_p", self.top_p),
            "top_k": params.get("top_k", self.top_k),
            "seed": params.get("seed", self.seed),
            "max_tokens": params.get("max_tokens", self.max_tokens),
            "repetition_penalty": params.get("repetition_penalty", self.repetition_penalty),
        }

        # Add model-specific parameters
        if "enable_search" in params:
            parameters["enable_search"] = params["enable_search"]

        if "result_format" in params:
            parameters["result_format"] = params["result_format"]

        if "response_format" in params:
            parameters["response_format"] = params["response_format"]

        # Add any additional model kwargs
        for key, value in self.model_kwargs.items():
            if key not in parameters:
                parameters[key] = value

        # Handle streaming
        if self.streaming and params.get("stream"):
            response = Generation.call(
                model=self.model_name,
                messages=messages,
                result_format='message',
                stream=True,
                **parameters
            )

            inner_completion = ''
            role = 'assistant'
            for chunk in response:
                if chunk.status_code == 200:
                    choice = chunk.output.choices[0]
                    role = choice['message'].get('role', role)
                    token = choice['message'].get('content', '')
                    inner_completion += token or ''
                    if run_manager:
                        run_manager.on_llm_new_token(token)
                else:
                    raise Exception(f"Error: {chunk.code}, {chunk.message}")

            message = AIMessage(content=inner_completion, role=role)
            return ChatResult(generations=[ChatGeneration(message=message)])
        else:
            # Non-streaming response
            response = Generation.call(
                model=self.model_name,
                messages=messages,
                result_format='message',
                **parameters
            )

            if response.status_code == 200:
                output = response.output
                usage = response.usage
                return self._create_chat_result(output, usage)
            else:
                raise Exception(f"Error: {response.code}, {response.message}")

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        message_dicts, params = self._create_message_dicts(messages, stop)
        params = {**params, **kwargs}
        if self.streaming:
            inner_completion = ''
            role = 'assistant'
            params['stream'] = True
            tool_calls: Optional[list[dict]] = None
            async for is_error, stream_resp in self.acompletion_with_retry(messages=message_dicts,
                                                                           **params):
                output = None
                msg = json.loads(stream_resp)
                if is_error:
                    logger.error(stream_resp)
                    raise ValueError(stream_resp)
                if 'output' in msg:
                    output = msg['output']
                choices = output.get('choices')
                if choices:
                    for choice in choices:
                        role = choice['message'].get('role', role)
                        token = choice['message'].get('content', '')
                        inner_completion += token or ''
                        _tool_calls = choice['message'].get('tool_calls')
                        if run_manager:
                            await run_manager.on_llm_new_token(token)
                        if _tool_calls:
                            if tool_calls is None:
                                tool_calls = _tool_calls
                            else:
                                tool_calls[0]['arguments'] += _tool_calls[0]['arguments']
            message = _convert_dict_to_message({
                'content': inner_completion,
                'role': role,
                'tool_calls': tool_calls,
            })
            return ChatResult(generations=[ChatGeneration(message=message)])
        else:
            response = [
                response
                async for _, response in self.acompletion_with_retry(messages=message_dicts,
                                                                     **params)
            ]
            response = json.loads(response[0])
            return self._create_chat_result(response.get('output'), response.get('usage'))

    def _create_message_dicts(
            self, messages: List[BaseMessage],
            stop: Optional[List[str]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        params = dict(self._client_params)
        if stop is not None:
            if 'stop' in params:
                raise ValueError('`stop` found in both the input and default params.')
            params['stop'] = stop

        message_dicts = [_convert_message_to_dict(m) for m in messages]

        return message_dicts, params

    def _create_chat_result(self, response: Mapping[str, Any], usage) -> ChatResult:
        generations = []
        for res in response['choices']:
            message = _convert_dict_to_message(res['message'])
            gen = ChatGeneration(message=message)
            generations.append(gen)

        llm_output = {'token_usage': usage, 'model_name': self.model_name}
        return ChatResult(generations=generations, llm_output=llm_output)

    @property
    def _identifying_params(self) -> Mapping[str, Any]:
        """Get the identifying parameters."""
        return {**{'model_name': self.model_name}, **self._default_params}

    @property
    def _client_params(self) -> Mapping[str, Any]:
        """Get the parameters used for the client."""
        return {**self._default_params}

    def _get_invocation_params(self,
                               stop: Optional[List[str]] = None,
                               **kwargs: Any) -> Dict[str, Any]:
        """Get the parameters used to invoke the model FOR THE CALLBACKS."""
        return {
            **super()._get_invocation_params(stop=stop, **kwargs),
            **self._default_params,
            'model': self.model_name,
            'function': kwargs.get('functions'),
        }

    @property
    def _llm_type(self) -> str:
        """Return type of chat model."""
        return 'qwen'

    def _get_encoding_model(self) -> Tuple[str, tiktoken.Encoding]:
        tiktoken_ = _import_tiktoken()
        if self.tiktoken_model_name is not None:
            model = self.tiktoken_model_name
        else:
            model = self.model_name
            # model chatglm-std, chatglm-lite
        # Returns the number of tokens used by a list of messages.
        try:
            encoding = tiktoken_.encoding_for_model(model)
        except KeyError:
            logger.warning('Warning: model not found. Using cl100k_base encoding.')
            model = 'cl100k_base'
            encoding = tiktoken_.get_encoding(model)
        return model, encoding

    def get_token_ids(self, text: str) -> List[int]:
        """Get the tokens present in the text with tiktoken package."""
        # tiktoken NOT supported for Python 3.7 or below
        if sys.version_info[1] <= 7:
            return super().get_token_ids(text)
        _, encoding_model = self._get_encoding_model()
        return encoding_model.encode(text)

    def get_num_tokens_from_messages(self, messages: List[BaseMessage]) -> int:
        """Calculate num tokens for chatglm with tiktoken package.

        todo: read chatglm document
        Official documentation: https://github.com/openai/openai-cookbook/blob/
        main/examples/How_to_format_inputs_to_ChatGPT_models.ipynb"""
        if sys.version_info[1] <= 7:
            return super().get_num_tokens_from_messages(messages)
        model, encoding = self._get_encoding_model()
        if model.startswith('chatglm'):
            # every message follows <im_start>{role/name}\n{content}<im_end>\n
            tokens_per_message = 4
            # if there's a name, the role is omitted
            tokens_per_name = -1
        else:
            raise NotImplementedError(
                f'get_num_tokens_from_messages() is not presently implemented '
                f'for model {model}.'
                'See https://github.com/openai/openai-python/blob/main/chatml.md for '
                'information on how messages are converted to tokens.')
        num_tokens = 0
        messages_dict = [_convert_message_to_dict(m) for m in messages]
        for message in messages_dict:
            num_tokens += tokens_per_message
            for key, value in message.items():
                num_tokens += len(encoding.encode(value))
                if key == 'name':
                    num_tokens += tokens_per_name
        # every reply is primed with <im_start>assistant
        num_tokens += 3
        return num_tokens

    @classmethod
    def _build_input_parameters(cls, model, messages, **kwargs):

        parameters = {}
        input = {}
        if messages is not None:
            msgs = copy.deepcopy(messages)
            input = {'messages': msgs}

        if model.startswith('qwen'):
            enable_search = kwargs.pop('enable_search', False)
            if enable_search:
                parameters['enable_search'] = enable_search
        elif model.startswith('bailian'):
            customized_model_id = kwargs.pop('customized_model_id', None)
            if customized_model_id is None:
                raise ValueError('customized_model_id is required for %s' % model)
            input['customized_model_id'] = customized_model_id

        if 'incremental_output' not in kwargs and kwargs.get('stream'):
            parameters['incremental_output'] = True

        return input, {**parameters, **kwargs}
