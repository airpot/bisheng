import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/bs-ui/tabs";

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { deleteKnowledgeApi, getKnowledgeListApi, updateKnowledgeApi } from '../../controllers/API'
import { Plus, Search } from 'lucide-react'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { PaginationComponent } from '../../components/PaginationComponent'
import { KnowledgeCard } from './components/KnowledgeCard'
import { CreateKnowledge } from './components/CreateKnowledge'
import { Skeleton } from '../../components/ui/skeleton'
import { message } from 'antd'
import { MergeKnowledgeDialog } from './components/MergeKnowledgeDialog'
import GenerateQAFromDoc from './components/GenerateQAFromDoc';

export interface Knowledge {
  id: number
  name: string
  description: string
  user_id: number
  user_name: string
  is_delete: number
  update_time: string
  create_time: string
  model: string
  collection_name: string
  index_name: string
  type: number
  copiable: boolean
}

export function KnowledgePage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [data, setData] = useState<Knowledge[]>([])
  const [loading, setLoading] = useState(true)
  const [searchValue, setSearchValue] = useState('')
  const [total, setTotal] = useState(0)
  const [currentPage, setCurrentPage] = useState(1)
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedKnowledges, setSelectedKnowledges] = useState<number[]>([])
  const [merging, setMerging] = useState(false)
  const pageSize = 20

  const init = () => {
    setLoading(true)
    getKnowledgeListApi(currentPage, pageSize, searchValue).then(res => {
      setData(res.data.data)
      setTotal(res.data.total)
      setLoading(false)
    }).catch(e => {
      message.error("获取知识库列表失败: " + e.response?.data?.detail || "未知错误")
      setLoading(false)
    })
  }

  useEffect(() => {
    init()
  }, [currentPage, searchValue])

  const handleDelete = async (id: number) => {
    try {
      await deleteKnowledgeApi(id)
      message.success('删除成功')
      init()
    } catch (e: any) {
      message.error(e.response?.data?.detail || "删除失败")
    }
  }

  const handleUpdate = async (id: number, values: { name: string; description: string }) => {
    try {
      await updateKnowledgeApi(id, values)
      message.success('更新成功')
      init()
    } catch (e: any) {
      message.error(e.response?.data?.detail || "更新失败")
    }
  }

  const handleSelect = (id: number, checked: boolean) => {
    if (checked) {
      setSelectedKnowledges(prev => [...prev, id])
    } else {
      setSelectedKnowledges(prev => prev.filter(kid => kid !== id))
    }
  }

  const handleGenerateQA = (data: any) => {
    // 处理生成的QA数据
    console.log('Generated QA data:', data);
    // 这里可以添加将生成的QA导入到QA知识库的逻辑
  };
  
  // 修改文件选择处理函数
  const handleFileSelect = (fileId: number, checked: boolean) => {
      if (checked) {
          setSelectedFileIds(prev => [...prev, fileId]);
      } else {
          setSelectedFileIds(prev => prev.filter(id => id !== fileId));
      }
  };
  
  // 全选处理函数
  const handleSelectAll = (checked: boolean) => {
      if (checked) {
          // 选择所有当前页的文件
          const currentPageFileIds = datalist.map(file => file.id);
          setSelectedFileIds(currentPageFileIds);
      } else {
          setSelectedFileIds([]);
      }
  };
  
  const handleMergeComplete = () => {
    setSelectedKnowledges([])
    init()
  }

  return (
    <div className="h-full">
      <div className="flex items-center justify-between mb-6">
        <div className="flex-1 flex items-center gap-4">
          <h1 className="text-2xl font-semibold">知识库</h1>
          <div className="relative w-64">
            <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="搜索知识库..."
              className="pl-8"
              value={searchValue}
              onChange={(e) => {
                setSearchValue(e.target.value)
                setCurrentPage(1)
              }}
            />
          </div>
        </div>
        <div className="flex items-center gap-2">
          {selectedKnowledges.length > 1 && (
            <MergeKnowledgeDialog
              knowledges={data}
              selectedKnowledges={selectedKnowledges}
              onMergeComplete={handleMergeComplete}
            >
              <Button variant="outline">合并知识库</Button>
            </MergeKnowledgeDialog>
          )}
          <Button className="flex items-center gap-2" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            新建知识库
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-40 rounded-lg" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {data.map(knowledge => (
              <KnowledgeCard
                key={knowledge.id}
                knowledge={knowledge}
                onDelete={handleDelete}
                onUpdate={handleUpdate}
                onSelect={handleSelect}
                isSelected={selectedKnowledges.includes(knowledge.id)}
                onSelectAll={handleSelectAll}
              />
            ))}
          </div>
          <div className="mt-8 flex justify-end">
            <PaginationComponent
              currentPage={currentPage}
              pageSize={pageSize}
              total={total}
              onChange={setCurrentPage}
            />
          </div>
        </>
      )}

      <CreateKnowledge open={createOpen} setOpen={setCreateOpen} onCreated={init} />
    </div>
  )
}

import KnowledgeFile from "./KnowledgeFile";
import KnowledgeQa from "./KnowledgeQa";


export default function index() {

    const { t } = useTranslation();

    const defaultValue = (() => {
        const page = window.LibPage;
        return page ? page.type : 'file'
    })();

    return (
        <div className="w-full h-full px-2 pt-4 relative">
            <Tabs defaultValue={defaultValue} className="w-full mb-[40px]">
                <TabsList className="">
                    <TabsTrigger value="file">{t('lib.fileData')}</TabsTrigger>
                    <TabsTrigger value="qa" className="roundedrounded-xl">{t('lib.qaData')}</TabsTrigger>
                </TabsList>
                <TabsContent value="qa">
                    <KnowledgeQa />
                </TabsContent>
                <TabsContent value="file">
                    <KnowledgeFile />
                </TabsContent>
            </Tabs>
        </div>
    );
}