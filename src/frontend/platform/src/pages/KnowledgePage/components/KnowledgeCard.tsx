import { useState } from 'react'
import { MoreHorizontal, BookOpen, FileText, Calendar, User, Edit, Trash2, Check } from 'lucide-react'
import { Button } from '../../../components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '../../../components/ui/dropdown-menu'
import { Knowledge } from '../index'
import { UpdateKnowledge } from './UpdateKnowledge'
import { useNavigate } from 'react-router-dom'
import { Checkbox } from '../../../components/ui/checkbox'

interface KnowledgeCardProps {
  knowledge: Knowledge
  onDelete: (id: number) => void
  onUpdate: (id: number, values: { name: string; description: string }) => void
  onSelect: (id: number, checked: boolean) => void
  isSelected: boolean
}

export function KnowledgeCard({ knowledge, onDelete, onUpdate, onSelect, isSelected }: KnowledgeCardProps) {
  const navigate = useNavigate()
  const [updateOpen, setUpdateOpen] = useState(false)

  return (
    <div className={`border rounded-lg p-4 flex flex-col relative ${isSelected ? 'ring-2 ring-blue-500' : ''}`}>
      <div className="flex justify-between items-start mb-3">
        <div className="flex items-start gap-2">
          <Checkbox
            checked={isSelected}
            onCheckedChange={(checked) => onSelect(knowledge.id, checked as boolean)}
          />
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold text-lg truncate" title={knowledge.name}>{knowledge.name}</h3>
            <p className="text-sm text-gray-500 truncate" title={knowledge.description}>{knowledge.description || '暂无描述'}</p>
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="h-8 w-8 p-0">
              <span className="sr-only">打开菜单</span>
              <MoreHorizontal className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => setUpdateOpen(true)}>
              <Edit className="mr-2 h-4 w-4" />
              编辑
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onDelete(knowledge.id)} className="text-red-600">
              <Trash2 className="mr-2 h-4 w-4" />
              删除
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="flex-1 space-y-2 mb-4">
        <div className="flex items-center text-sm text-gray-500">
          <BookOpen className="mr-2 h-4 w-4" />
          <span>{knowledge.model}</span>
        </div>
        <div className="flex items-center text-sm text-gray-500">
          <User className="mr-2 h-4 w-4" />
          <span>{knowledge.user_name}</span>
        </div>
        <div className="flex items-center text-sm text-gray-500">
          <Calendar className="mr-2 h-4 w-4" />
          <span>{new Date(knowledge.update_time).toLocaleString()}</span>
        </div>
      </div>

      <Button 
        variant="outline" 
        className="w-full"
        onClick={() => navigate(`/knowledge/${knowledge.id}`)}
      >
        <FileText className="mr-2 h-4 w-4" />
        查看文件
      </Button>

      <UpdateKnowledge
        open={updateOpen}
        setOpen={setUpdateOpen}
        knowledge={knowledge}
        onUpdated={(id, values) => {
          onUpdate(id, values)
          setUpdateOpen(false)
        }}
      />
    </div>
  )
}