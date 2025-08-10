import json
import urllib.parse
from datetime import datetime
from io import BytesIO
from typing import List, Optional, Any

import pandas as pd
from fastapi import (APIRouter, BackgroundTasks, Body, Depends, File, HTTPException, Query, Request,
                     UploadFile)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse

from bisheng.api.errcode.base import UnAuthorizedError
from bisheng.api.errcode.knowledge import KnowledgeCPError, KnowledgeQAError
from bisheng.api.services import knowledge_imp
from bisheng.api.services.knowledge import KnowledgeService
from bisheng.api.services.knowledge_imp import add_qa
from bisheng.api.services.user_service import UserPayload, get_login_user
from bisheng.api.v1.schemas import (KnowledgeFileProcess, UpdatePreviewFileChunk, UploadFileResponse,
                                    resp_200, resp_500)
from bisheng.cache.utils import save_uploaded_file
from bisheng.database.models.knowledge import (KnowledgeCreate, KnowledgeDao, KnowledgeTypeEnum, KnowledgeUpdate,
                                              update_file_tags, get_all_tags)
from bisheng.database.models.knowledge_file import (KnowledgeFileDao, KnowledgeFileStatus,
                                                    QAKnoweldgeDao, QAKnowledgeUpsert, QAStatus)
from bisheng.database.models.llm_server import LLMModel
from bisheng.database.models.role_access import AccessType
from bisheng.database.models.user import UserDao
from bisheng.utils.logger import logger
from bisheng.worker.knowledge.qa import insert_qa_celery

# build router
router = APIRouter(prefix='/knowledge', tags=['Knowledge'])

# 配置API请求超时时间
REQUEST_TIMEOUT = 60  # 增加到60秒，适应更复杂的查询
MAX_TOKENS = 2048     # 保持最大token数合理

# 在查询函数中添加超时处理
def search_knowledge(query: str, timeout: int = REQUEST_TIMEOUT):
    try:
        # 实现带超时的查询逻辑
        with timeout_decorator(timeout):
            results = vector_store.search(query)
            return results
    except TimeoutError:
        logger.error("Search request timed out")
        raise HTTPException(status_code=504, detail="Search request timed out")


@router.post('/upload')
async def upload_file(*, file: UploadFile = File(...)):
    try:
        file_name = file.filename
        # 缓存本地
        uuid_file_name = KnowledgeService.save_upload_file_original_name(file_name)
        file_path = save_uploaded_file(file.file, 'bisheng', uuid_file_name)
        if not isinstance(file_path, str):
            file_path = str(file_path)
        return resp_200(UploadFileResponse(file_path=file_path))
    except Exception as exc:
        logger.exception(f'Error saving file: {exc}')
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/preview')
async def preview_file_chunk(*,
                             request: Request,
                             login_user: UserPayload = Depends(get_login_user),
                             req_data: KnowledgeFileProcess):
    """ 获取某个文件的分块预览内容 """
    try:
        parse_type, file_share_url, res, partitions = KnowledgeService.get_preview_file_chunk(
            request, login_user, req_data)
        return resp_200(
            data={
                'parse_type': parse_type,
                'file_url': file_share_url,
                'chunks': res,
                'partitions': partitions
            })
    except HTTPException as e:
        raise e
    except Exception as e:
        # productor hope raise this tips
        logger.exception('preview_file_chunk_error')
        return resp_500(message="文档解析失败")


@router.put('/preview')
async def update_preview_file_chunk(*,
                                    request: Request,
                                    login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 更新某个文件的分块预览内容 """

    res = KnowledgeService.update_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.delete('/preview')
async def delete_preview_file_chunk(*,
                                    request: Request,
                                    login_user: UserPayload = Depends(get_login_user),
                                    req_data: UpdatePreviewFileChunk):
    """ 删除某个文件的分块预览内容 """

    res = KnowledgeService.delete_preview_file_chunk(request, login_user, req_data)
    return resp_200(res)


@router.post('/process')
async def process_knowledge_file(*,
                                 request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 background_tasks: BackgroundTasks,
                                 req_data: KnowledgeFileProcess):
    """ 上传文件到知识库内 """
    res = KnowledgeService.process_knowledge_file(request, login_user, background_tasks, req_data)
    return resp_200(res)


@router.post('/create')
def create_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge: KnowledgeCreate):
    """ 创建知识库. """
    db_knowledge = KnowledgeService.create_knowledge(request, login_user, knowledge)
    return resp_200(db_knowledge)


@router.post('/copy')
async def copy_knowledge(*,
                         request: Request,
                         background_tasks: BackgroundTasks,
                         login_user: UserPayload = Depends(get_login_user),
                         knowledge_id: int = Body(..., embed=True)):
    """ 复制知识库. """
    knowledge = KnowledgeDao.query_by_id(knowledge_id)

    if not login_user.is_admin and knowledge.user_id != login_user.id:
        return UnAuthorizedError.return_resp()

    knowledge_count = KnowledgeFileDao.count_file_by_filters(
        knowledge_id,
        status=KnowledgeFileStatus.PROCESSING.value,
    )
    if knowledge.state != 1 or knowledge_count > 0:
        return KnowledgeCPError.return_resp()
    knowledge = KnowledgeService.copy_knowledge(request, background_tasks, login_user, knowledge)
    return resp_200(knowledge)


@router.post('/merge')
async def merge_knowledge(*,
                          request: Request,
                          login_user: UserPayload = Depends(get_login_user),
                          source_ids: List[int] = Body(..., embed=True),
                          target_id: int = Body(..., embed=True),
                          target_name: str = Body(None, embed=True),
                          duplicate_handler: str = Body("skip", embed=True)):
    """ 合并知识库: 
    source_ids: 源知识库ID列表
    target_id: 目标知识库ID
    target_name: 目标知识库新名称（可选）
    duplicate_handler: 重复文档处理方式 ("skip"/"overwrite"/"rename")
    """
    # 检查目标知识库是否存在且用户有权限
    target_knowledge = KnowledgeDao.query_by_id(target_id)
    if not target_knowledge:
        raise HTTPException(status_code=404, detail="目标知识库不存在")
    
    if not login_user.access_check(
        target_knowledge.user_id, str(target_id), AccessType.KNOWLEDGE_WRITE
    ):
        raise UnAuthorizedError.http_exception()
    
    # 检查源知识库是否存在且用户有权限
    source_knowledges = KnowledgeDao.get_list_by_ids(source_ids)
    for source_knowledge in source_knowledges:
        if not source_knowledge:
            raise HTTPException(status_code=404, detail=f"源知识库不存在: {source_id}")
        
        if not login_user.access_check(
            source_knowledge.user_id, str(source_knowledge.id), AccessType.KNOWLEDGE
        ):
            raise UnAuthorizedError.http_exception()
    
    try:
        # 执行合并操作
        merged_count = KnowledgeDao.merge_knowledge(source_ids, target_id, target_name, duplicate_handler)
        return resp_200(data={"merged_count": merged_count, "message": f"成功合并{merged_count}个文档"})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("知识库合并失败")
        raise HTTPException(status_code=500, detail="知识库合并失败")


@router.get('', status_code=200)
def get_knowledge(*,
                  request: Request,
                  login_user: UserPayload = Depends(get_login_user),
                  name: str = None,
                  knowledge_type: int = Query(default=KnowledgeTypeEnum.NORMAL.value,
                                              alias='type'),
                  page_size: Optional[int] = 10,
                  page_num: Optional[int] = 1):
    """ 读取所有知识库信息. """
    knowledge_type = KnowledgeTypeEnum(knowledge_type)
    res, total = KnowledgeService.get_knowledge(request, login_user, knowledge_type, name,
                                                page_num, page_size)
    return resp_200(data={'data': res, 'total': total})


@router.get('/info', status_code=200)
def get_knowledge_info(*,
                       request: Request,
                       login_user: UserPayload = Depends(get_login_user),
                       knowledge_id: List[int] = Query(...)):
    """ 根据知识库ID读取知识库信息. """
    res = KnowledgeService.get_knowledge_info(request, login_user, knowledge_id)
    return resp_200(data=res)


@router.put('/', status_code=200)
async def update_knowledge(*,
                           request: Request,
                           login_user: UserPayload = Depends(get_login_user),
                           knowledge: KnowledgeUpdate):
    res = KnowledgeService.update_knowledge(request, login_user, knowledge)
    return resp_200(data=res)


@router.delete('/', status_code=200)
def delete_knowledge(*,
                     request: Request,
                     login_user: UserPayload = Depends(get_login_user),
                     knowledge_id: int = Body(..., embed=True)):
    """ 删除知识库信息. """

    KnowledgeService.delete_knowledge(request, login_user, knowledge_id)
    return resp_200(message='删除成功')


@router.get('/file_list/{knowledge_id}', status_code=200)
def get_filelist(*,
                 request: Request,
                 login_user: UserPayload = Depends(get_login_user),
                 file_name: str = None,
                 file_ids: list[int] = None,
                 knowledge_id: int = 0,
                 page_size: int = 10,
                 page_num: int = 1,
                 status: Optional[int] = None):
    """ 获取知识库文件信息. """
    data, total, flag = KnowledgeService.get_knowledge_files(request, login_user, knowledge_id,
                                                             file_name, status, page_num,
                                                             page_size, file_ids)

    return resp_200({
        'data': data,
        'total': total,
        'writeable': flag,
    })


@router.get('/qa/list/{qa_knowledge_id}', status_code=200)
def get_QA_list(*,
                qa_knowledge_id: int,
                page_size: int = 10,
                page_num: int = 1,
                question: Optional[str] = None,
                answer: Optional[str] = None,
                keyword: Optional[str] = None,
                status: Optional[int] = None,
                login_user: UserPayload = Depends(get_login_user)):
    """ 获取知识库文件信息. """
    db_knowledge = KnowledgeService.judge_qa_knowledge_write(login_user, qa_knowledge_id)

    qa_list, total_count = knowledge_imp.list_qa_by_knowledge_id(qa_knowledge_id, page_size,
                                                                 page_num, question, answer,
                                                                 keyword, status)
    user_list = UserDao.get_user_by_ids([qa.user_id for qa in qa_list])
    user_map = {user.user_id: user.user_name for user in user_list}
    data = [jsonable_encoder(qa) for qa in qa_list]
    for qa in data:
        qa['questions'] = qa['questions'][0]
        qa['answers'] = json.loads(qa['answers'])[0]
        qa['user_name'] = user_map.get(qa['user_id'], qa['user_id'])

    return resp_200({
        'data':
            data,
        'total':
            total_count,
        'writeable':
            login_user.access_check(db_knowledge.user_id, str(qa_knowledge_id),
                                    AccessType.KNOWLEDGE_WRITE)
    })


@router.post('/retry', status_code=200)
def retry(*,
          request: Request,
          login_user: UserPayload = Depends(get_login_user),
          background_tasks: BackgroundTasks,
          req_data: dict):
    """失败重试"""
    KnowledgeService.retry_files(request, login_user, background_tasks, req_data)
    return resp_200()


@router.delete('/file/{file_id}', status_code=200)
def delete_knowledge_file(*,
                          request: Request,
                          file_id: int,
                          login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """
    KnowledgeService.delete_knowledge_file(request, login_user, [file_id])
    return resp_200(message='删除成功')


@router.get('/chunk', status_code=200)
async def get_knowledge_chunk(request: Request,
                              login_user: UserPayload = Depends(get_login_user),
                              knowledge_id: int = Query(..., description='知识库ID'),
                              file_ids: List[int] = Query(default=[], description='文件ID'),
                              keyword: str = Query(default='', description='关键字'),
                              page: int = Query(default=1, description='页数'),
                              limit: int = Query(default=10, description='每页条数条数')):
    """ 获取知识库分块内容 """
    # 为了解决keyword参数有时候没有进行urldecode的bug
    if keyword.startswith('%'):
        keyword = urllib.parse.unquote(keyword)
    res, total = KnowledgeService.get_knowledge_chunks(request, login_user, knowledge_id, file_ids,
                                                       keyword, page, limit)
    return resp_200(data={'data': res, 'total': total})


@router.put('/chunk', status_code=200)
async def update_knowledge_chunk(request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号'),
                                 text: str = Body(..., embed=True, description='分块内容'),
                                 bbox: str = Body(default='', embed=True, description='分块框选位置')):
    """ 更新知识库分块内容 """
    KnowledgeService.update_knowledge_chunk(request, login_user, knowledge_id, file_id,
                                            chunk_index, text, bbox)
    return resp_200()


@router.delete('/chunk', status_code=200)
async def delete_knowledge_chunk(request: Request,
                                 login_user: UserPayload = Depends(get_login_user),
                                 knowledge_id: int = Body(..., embed=True, description='知识库ID'),
                                 file_id: int = Body(..., embed=True, description='文件ID'),
                                 chunk_index: int = Body(..., embed=True, description='分块索引号')):
    """ 删除知识库分块内容 """
    KnowledgeService.delete_knowledge_chunk(request, login_user, knowledge_id, file_id,
                                            chunk_index)
    return resp_200()


@router.get('/file_share')
async def get_file_share_url(request: Request,
                             login_user: UserPayload = Depends(get_login_user),
                             file_id: int = Query(description='文件唯一ID')):
    url = KnowledgeService.get_file_share_url(file_id)
    return resp_200(data=url)


@router.get('/file_bbox')
async def get_file_bbox(request: Request,
                        login_user: UserPayload = Depends(get_login_user),
                        file_id: int = Query(description='文件唯一ID')):
    res = KnowledgeService.get_file_bbox(request, login_user, file_id)
    return resp_200(data=res)


@router.post('/qa/add', status_code=200)
async def qa_add(*, QACreate: QAKnowledgeUpsert,
                 login_user: UserPayload = Depends(get_login_user)):
    """ 增加知识库信息. """
    QACreate.user_id = login_user.user_id
    db_knowledge = KnowledgeDao.query_by_id(QACreate.knowledge_id)
    if db_knowledge.type != KnowledgeTypeEnum.QA.value:
        raise HTTPException(status_code=404, detail='知识库类型错误')

    db_q = QAKnoweldgeDao.get_qa_knowledge_by_name(QACreate.questions, QACreate.knowledge_id, exclude_id=QACreate.id)
    # create repeat question or update
    if (db_q and not QACreate.id) or (db_q and QACreate.id and db_q.id != QACreate.id):
        raise KnowledgeQAError.http_exception()

    add_qa(db_knowledge=db_knowledge, data=QACreate)
    return resp_200()


@router.post('/qa/status_switch', status_code=200)
def qa_status_switch(*,
                     status: int = Body(embed=True),
                     id: int = Body(embed=True),
                     login_user: UserPayload = Depends(get_login_user)):
    """ 修改知识库信息. """
    new_qa_db = knowledge_imp.qa_status_change(id, status)
    if not new_qa_db:
        return resp_200()
    if new_qa_db.status != status:
        # 说明状态切换失败
        return resp_500(message=f'状态切换失败: {new_qa_db.remark}')
    return resp_200()


@router.get('/qa/detail', status_code=200)
def qa_list(*, id: int, login_user: UserPayload = Depends(get_login_user)):
    """ 增加知识库信息. """
    qa_knowledge = QAKnoweldgeDao.get_qa_knowledge_by_primary_id(id)
    qa_knowledge.answers = json.loads(qa_knowledge.answers)[0]
    return resp_200(data=qa_knowledge)


@router.post('/qa/append', status_code=200)
def qa_append(
        *,
        ids: list[int] = Body(..., embed=True),
        question: str = Body(..., embed=True),
        login_user: UserPayload = Depends(get_login_user),
):
    """ 增加知识库信息. """
    QA_list = QAKnoweldgeDao.select_list(ids)
    knowledge = KnowledgeDao.query_by_id(QA_list[0].knowledge_id)
    for q in QA_list:
        if question in q.questions:
            raise KnowledgeQAError.http_exception()
    for qa in QA_list:
        qa.questions.append(question)
        knowledge_imp.add_qa(knowledge, qa)
    return resp_200()


@router.delete('/qa/delete', status_code=200)
def qa_delete(*,
              ids: list[int] = Body(embed=True),
              login_user: UserPayload = Depends(get_login_user)):
    """ 删除知识文件信息 """
    knowledge_dbs = QAKnoweldgeDao.select_list(ids)
    knowledge = KnowledgeDao.query_by_id(knowledge_dbs[0].knowledge_id)
    if not login_user.access_check(knowledge.user_id, str(knowledge.id),
                                   AccessType.KNOWLEDGE_WRITE):
        raise HTTPException(status_code=404, detail='没有权限执行操作')

    if knowledge.type == KnowledgeTypeEnum.NORMAL.value:
        return HTTPException(status_code=500, detail='知识库类型错误')

    knowledge_imp.delete_vector_data(knowledge, ids)
    QAKnoweldgeDao.delete_batch(ids)
    return resp_200()


@router.post('/qa/auto_question')
def qa_auto_question(
        *,
        number: int = Body(default=3, embed=True),
        ori_question: str = Body(default='', embed=True),
        answer: str = Body(default='', embed=True),
):
    """通过大模型自动生成问题"""
    questions = knowledge_imp.recommend_question(ori_question, number=number, answer=answer)
    return resp_200(data={'questions': questions})


@router.get('/qa/export/template', status_code=200)
def get_export_url():
    data = [{"问题": "", "答案": "", "相似问题1": "", "相似问题2": ""}]
    df = pd.DataFrame(data)
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Sheet1", index=False)
    file_name = f"QA知识库导入模板.xlsx"
    file_path = save_uploaded_file(bio, 'bisheng', file_name)
    return resp_200({"url": file_path})


@router.get('/qa/export/{qa_knowledge_id}', status_code=200)
def get_export_url(*,
                   qa_knowledge_id: int,
                   question: Optional[str] = None,
                   answer: Optional[str] = None,
                   keyword: Optional[str] = None,
                   status: Optional[int] = None,
                   max_lines: Optional[int] = 10000,
                   login_user: UserPayload = Depends(get_login_user)):
    # 查询当前知识库，是否有写入权限
    db_knowledge = KnowledgeService.judge_qa_knowledge_write(login_user, qa_knowledge_id)

    if keyword:
        question = keyword

    def get_qa_source(source):
        '0: 未知 1: 手动；2: 审计, 3: api'
        if int(source) == 1:
            return "手动创建"
        elif int(source) == 2:
            return "审计创建"
        elif int(source) == 3:
            return "api创建"
        return "未知"

    def get_status(statu):
        if int(statu) == 1:
            return "开启"
        return "关闭"

    page_num = 1
    total_num = 0
    page_size = max_lines
    user_list = UserDao.get_all_users()
    user_map = {user.user_id: user.user_name for user in user_list}
    file_list = []
    file_pr = datetime.now().strftime('%Y%m%d%H%M%S')
    file_index = 1
    while True:
        qa_list, total_count = knowledge_imp.list_qa_by_knowledge_id(qa_knowledge_id, page_size,
                                                                     page_num, question, answer,
                                                                     status)

        data = [jsonable_encoder(qa) for qa in qa_list]
        qa_dict_list = []
        all_title = ["问题", "答案"]
        for qa in data:
            qa_dict_list.append({
                "问题": qa['questions'][0],
                "答案": json.loads(qa['answers'])[0],
                # "类型":get_qa_source(qa['source']),
                # "创建时间":qa['create_time'],
                # "更新时间":qa['update_time'],
                # "创建者":user_map.get(qa['user_id'], qa['user_id']),
                # "状态":get_status(qa['status']),
            })
            for index, question in enumerate(qa['questions']):
                if index == 0:
                    continue
                key = f"相似问题{index}"
                if key not in all_title:
                    all_title.append(key)
                qa_dict_list[-1][key] = question
        if len(qa_dict_list) != 0:
            df = pd.DataFrame(qa_dict_list)
        else:
            df = pd.DataFrame([{"问题": "", "答案": "", "相似问题1": "", "相似问题2": ""}])
        df = df[all_title]
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Sheet1", index=False)
        file_name = f"{file_pr}_{file_index}.xlsx"
        file_index = file_index + 1
        file_path = save_uploaded_file(bio, 'bisheng', file_name)
        file_list.append(file_path)
        total_num += len(qa_list)
        if len(qa_list) < page_size or total_num >= total_count:
            break

    return resp_200({"file_list": file_list})


def convert_excel_value(value: Any):
    if value is None or value == "":
        return ''
    if str(value) == 'nan' or str(value) == 'null':
        return ''
    return str(value)


@router.post('/qa/preview/{qa_knowledge_id}', status_code=200)
def post_import_file(*,
                     qa_knowledge_id: int,
                     file_url: str = Body(..., embed=True),
                     size: Optional[int] = Body(default=0, embed=True),
                     offset: Optional[int] = Body(default=0, embed=True),
                     login_user: UserPayload = Depends(get_login_user)):
    df = pd.read_excel(file_url)
    columns = df.columns.to_list()
    if '答案' not in columns or '问题' not in columns:
        raise HTTPException(status_code=500, detail='文件格式错误，没有 ‘问题’ 或 ‘答案’ 列')
    data = df.T.to_dict().values()
    insert_data = []
    for dd in data:
        d = QAKnowledgeUpsert(
            user_id=login_user.user_id,
            knowledge_id=qa_knowledge_id,
            answers=[convert_excel_value(dd['答案'])],
            questions=[convert_excel_value(dd['问题'])],
            source=4,
            create_time=datetime.now(),
            update_time=datetime.now())
        for key, value in dd.items():
            if key.startswith('相似问题') and convert_excel_value(value):
                d.questions.append(convert_excel_value(value))
        insert_data.append(d)
    try:
        if size > 0 and offset >= 0:
            if offset >= len(insert_data):
                insert_data = []
            else:
                insert_data = insert_data[offset:size]
    except Exception as e:
        raise HTTPException(status_code=500, detail=e)
    return resp_200({"result": insert_data})


@router.post('/qa/import/{qa_knowledge_id}', status_code=200)
def post_import_file(*,
                     qa_knowledge_id: int,
                     file_list: list[str] = Body(..., embed=True),
                     background_tasks: BackgroundTasks,
                     login_user: UserPayload = Depends(get_login_user)):
    # 查询当前知识库，是否有写入权限
    db_knowledge = KnowledgeService.judge_qa_knowledge_write(login_user, qa_knowledge_id)

    insert_result = []
    error_result = []
    have_question = []
    for file_url in file_list:
        df = pd.read_excel(file_url)
        columns = df.columns.to_list()
        if '答案' not in columns or '问题' not in columns:
            insert_result.append(0)
            continue
        data = df.T.to_dict().values()
        insert_data = []
        have_data = []
        all_questions = set()
        for index, dd in enumerate(data):
            tmp_questions = set()
            dd_question = convert_excel_value(dd['问题'])
            dd_answer = convert_excel_value(dd['答案'])
            QACreate = QAKnowledgeUpsert(
                user_id=login_user.user_id,
                knowledge_id=qa_knowledge_id,
                answers=[dd_answer],
                questions=[dd_question],
                source=4,
                status=QAStatus.PROCESSING.value)
            tmp_questions.add(QACreate.questions[0])
            for key, value in dd.items():
                if key.startswith('相似问题'):
                    if tmp_value := convert_excel_value(value):
                        if tmp_value not in tmp_questions:
                            QACreate.questions.append(tmp_value)
                            tmp_questions.add(tmp_value)

            db_q = QAKnoweldgeDao.get_qa_knowledge_by_name(QACreate.questions, QACreate.knowledge_id)
            if (db_q and not QACreate.id) or len(tmp_questions & all_questions) > 0 or not dd_question or not dd_answer:
                have_data.append(index)
            else:
                insert_data.append(QACreate)
                all_questions = all_questions | tmp_questions
        result = QAKnoweldgeDao.batch_insert_qa(insert_data)

        # async task add qa into milvus and es
        for one in result:
            insert_qa_celery.delay(one.id)

        error_result.append(have_data)

    return resp_200({"errors": error_result})


@router.get('/file/export/{knowledge_id}', status_code=200)
async def export_knowledge_files(*,
                                 knowledge_id: int,
                                 login_user: UserPayload = Depends(get_login_user)):
    """导出知识库文件信息"""
    db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    
    if not login_user.access_check(
        db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE
    ):
        raise UnAuthorizedError.http_exception()
    
    # 获取知识库下的所有文件
    files = KnowledgeFileDao.get_file_by_filters(knowledge_id=knowledge_id)
    
    # 准备CSV数据
    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['文档名称', '文档摘要'])  # CSV header
    for file in files:
        writer.writerow([file.file_name, file.remark])  # 写入文件名和摘要信息
    
    output.seek(0)
    
    # 返回CSV文件
    headers = {"Content-Disposition": f"attachment; filename=knowledge_files_{knowledge_id}.csv"}
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers=headers
    )


@router.get('/file/vector/export/{knowledge_id}', status_code=200)
async def export_knowledge_vectors(*,
                                   knowledge_id: int,
                                   login_user: UserPayload = Depends(get_login_user)):
    """导出知识库向量数据"""
    db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    
    if not login_user.access_check(
        db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE
    ):
        raise UnAuthorizedError.http_exception()
    
    # 获取知识库向量数据
    from bisheng.interface.embeddings.custom import FakeEmbedding
    from bisheng.api.services.knowledge_imp import decide_vectorstores
    
    # 初始化向量库连接
    embeddings = FakeEmbedding()
    vector_client = decide_vectorstores(db_knowledge.collection_name, "Milvus", embeddings)
    
    # 从向量库中查询数据
    if vector_client and vector_client.col:
        # 获取除了主键、向量和bbox之外的所有字段
        fields = [
            s.name for s in vector_client.col.schema.fields
            if s.name not in ['pk', 'vector', 'bbox']
        ]
        
        # 查询所有向量数据
        res_list = vector_client.col.query(
            expr=f'knowledge_id=="{knowledge_id}"', 
            output_fields=fields,
            limit=10000  # 限制返回数量，防止数据过大
        )
        
        # 准备CSV数据
        import csv
        import io
        import json
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 写入表头
        if res_list:
            headers = list(res_list[0].keys())
            writer.writerow(headers)
            
            # 写入数据行
            for item in res_list:
                row = []
                for header in headers:
                    value = item.get(header, '')
                    # 如果是字典或列表，转换为JSON字符串
                    if isinstance(value, (dict, list)):
                        row.append(json.dumps(value, ensure_ascii=False))
                    else:
                        row.append(value)
                writer.writerow(row)
        
        output.seek(0)
        
        # 返回CSV文件
        headers = {"Content-Disposition": f"attachment; filename=knowledge_vectors_{knowledge_id}.csv"}
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers=headers
        )
    else:
        raise HTTPException(status_code=400, detail="向量数据库连接失败")


@router.post('/file/vector/import/{knowledge_id}', status_code=200)
async def import_knowledge_vectors(*,
                                   knowledge_id: int,
                                   file: UploadFile = File(...),
                                   login_user: UserPayload = Depends(get_login_user)):
    """导入知识库向量数据"""
    db_knowledge = KnowledgeDao.query_by_id(knowledge_id)
    if not db_knowledge:
        raise HTTPException(status_code=404, detail="知识库不存在")
    
    if not login_user.access_check(
        db_knowledge.user_id, str(knowledge_id), AccessType.KNOWLEDGE_WRITE
    ):
        raise UnAuthorizedError.http_exception()
    
    try:
        # 读取上传的CSV文件
        content = await file.read()
        csv_file = io.StringIO(content.decode('utf-8'))
        reader = csv.DictReader(csv_file)
        vector_data = [dict(row) for row in reader]
        
        if not vector_data:
            raise HTTPException(status_code=400, detail="CSV文件为空")
        
        # 获取向量库连接
        from bisheng.interface.embeddings.custom import FakeEmbedding
        from bisheng.api.services.knowledge_imp import decide_vectorstores
        
        embeddings = FakeEmbedding()
        vector_client = decide_vectorstores(db_knowledge.collection_name, "Milvus", embeddings)
        
        if not vector_client or not vector_client.col:
            raise HTTPException(status_code=400, detail="向量数据库连接失败")
        
        # 准备插入数据
        import json
        insert_data = []
        for item in vector_data:
            processed_item = {}
            for key, value in item.items():
                # 尝试解析JSON字符串
                try:
                    processed_item[key] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    processed_item[key] = value
            
            # 确保knowledge_id正确
            processed_item['knowledge_id'] = str(knowledge_id)
            insert_data.append(processed_item)
        
        # 插入数据到向量库
        if insert_data:
            # 获取字段信息
            field_names = [field.name for field in vector_client.col.schema.fields]
            
            # 过滤数据，只保留存在的字段
            filtered_data = []
            for item in insert_data:
                filtered_item = {k: v for k, v in item.items() if k in field_names}
                filtered_data.append(filtered_item)
            
            # 插入数据
            vector_client.col.insert(filtered_data)
            vector_client.col.flush()
        
        return resp_200(data={"message": "导入成功", "count": len(vector_data)})
        
    except Exception as e:
        logger.exception("导入向量数据失败")
        raise HTTPException(status_code=500, detail=f"导入失败: {str(e)}")


@app.get("/api/v1/knowledge/models")
async def get_available_models():
    """获取可用的模型列表"""
    # 从数据库获取所有已添加的模型
    db_session = next(get_session())
    llm_models = db_session.query(LLMModel).filter(
        LLMModel.model_type == 'llm',
        LLMModel.online == True
    ).all()
    
    # 构造返回格式
    models = []
    for model in llm_models:
        models.append({
            "id": model.model_name, 
            "name": f"{model.name} ({model.model_name})"
        })
    
    return {"models": models}

# 新增标签管理接口
@app.post("/api/v1/knowledge/file/{file_id}/tags")
async def update_file_tags_endpoint(file_id: int, request: Dict[str, Any] = Body(...)):
    """更新文件标签"""
    # 获取请求参数
    tags = request.get("tags", [])
    model_name = request.get("model_name", "qwen-plus")  # 默认使用qwen-plus模型
    
    # 实现标签更新逻辑
    db_session = next(get_session())
    file = db_session.query(KnowledgeFile).filter(KnowledgeFile.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    
    # 调用大模型生成标签（可选）
    if tags and len(tags) == 1 and tags[0].startswith("auto:"):
        # 这里应该加载文件内容，为了简化示例直接跳过
        # content = file_loader.load_file_content(file.file_path)
        # tags = llm_service.generate_tags(content, model_name)  # 使用指定模型生成标签
        # 临时示例标签
        tags = ["示例标签1", "示例标签2", "示例标签3"]
    
    updated_file = update_file_tags(db_session, file_id, tags)
    if updated_file:
        return {"status": "success", "tags": tags, "file": updated_file.to_dict()}
    else:
        raise HTTPException(status_code=404, detail="File not found")

@app.get("/api/v1/knowledge/{knowledge_id}/tags")
async def get_knowledge_tags_endpoint(knowledge_id: int):
    """获取知识库中所有标签"""
    db_session = next(get_session())
    tags = get_all_tags(db_session, knowledge_id)
    return {"tags": tags}
