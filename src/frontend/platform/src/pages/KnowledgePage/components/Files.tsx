import { Link, useParams } from "react-router-dom";
import { Button } from "../../../components/bs-ui/button";
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow
} from "../../../components/bs-ui/table";
import { useState } from "react";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { Download, Filter, RotateCw, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchInput } from "../../../components/bs-ui/input";
import AutoPagination from "../../../components/bs-ui/pagination/autoPagination";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger } from "../../../components/bs-ui/select";
import { deleteFile, readFileByLibDatabase, retryKnowledgeFileApi } from "../../../components/bs-ui/table";
import { captureAndAlertRequestErrorHoc } from "../../../controllers/request";
import { useTable } from "../../../util/hook";
import { LoadingIcon } from "@/components/bs-icons/loading";
import useKnowledgeStore from "../useKnowledgeStore";
import { truncateString } from "@/util/utils";
import { exportKnowledgeFileApi, exportKnowledgeVectorApi, importKnowledgeVectorApi } from "@/controllers/API";

// 添加标签管理组件
interface TagInputProps {
  fileId: number;
  tags: string[];
  onTagsUpdate: (fileId: number, newTags: string[]) => void;
}

const TagInput: React.FC<TagInputProps> = ({ fileId, tags, onTagsUpdate }) => {
  const [editTags, setEditTags] = useState<string[]>(tags || []);
  const [inputValue, setInputValue] = useState('');
  const [selectedModel, setSelectedModel] = useState('qwen-plus');
  const [availableModels, setAvailableModels] = useState([]);

  // 获取可用模型列表
  useEffect(() => {
    const fetchModels = async () => {
      try {
        const response = await fetch('/api/v1/knowledge/models');
        const result = await response.json();
        setAvailableModels(result.models);
        // 设置默认模型
        if (result.models.length > 0) {
          setSelectedModel(result.models[0].id);
        }
      } catch (error) {
        console.error('Failed to fetch models:', error);
        // 如果获取失败，使用默认模型列表
        const defaultModels = [
          {"id": "qwen-turbo", "name": "Qwen Turbo"},
          {"id": "qwen-plus", "name": "Qwen Plus"},
          {"id": "qwen-max", "name": "Qwen Max"},
          {"id": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"},
          {"id": "gpt-4", "name": "GPT-4"}
        ];
        setAvailableModels(defaultModels);
        setSelectedModel("qwen-plus");
      }
    };
    
    fetchModels();
  }, []);

  const handleAddTag = () => {
    if (inputValue && !editTags.includes(inputValue)) {
      const newTags = [...editTags, inputValue];
      setEditTags(newTags);
      setInputValue('');
    }
  };

  const handleRemoveTag = (tag: string) => {
    const newTags = editTags.filter(t => t !== tag);
    setEditTags(newTags);
  };

  const handleSave = async () => {
    try {
      const response = await fetch(`/api/v1/knowledge/file/${fileId}/tags`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          tags: editTags,
          model_name: selectedModel
        }),
      });
      
      const result = await response.json();
      if (result.status === 'success') {
        onTagsUpdate(fileId, result.tags);
      }
    } catch (error) {
      console.error('Failed to save tags:', error);
    }
  };

  const handleAutoGenerate = async () => {
    try {
      const response = await fetch(`/api/v1/knowledge/file/${fileId}/tags`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          tags: ['auto:generate'],
          model_name: selectedModel
        }),
      });
      
      const result = await response.json();
      if (result.status === 'success') {
        setEditTags(result.tags);
        onTagsUpdate(fileId, result.tags);
      }
    } catch (error) {
      console.error('Failed to generate tags:', error);
    }
  };

  return (
    <div style={{ marginTop: '10px', padding: '10px', border: '1px solid #ddd', borderRadius: '4px' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '5px', marginBottom: '10px' }}>
        {editTags.map(tag => (
          <span 
            key={tag} 
            style={{ 
              background: '#e1f5fe', 
              padding: '2px 8px', 
              borderRadius: '12px', 
              display: 'flex', 
              alignItems: 'center' 
            }}
          >
            {tag}
            <button 
              onClick={() => handleRemoveTag(tag)} 
              style={{ 
                background: 'none', 
                border: 'none', 
                marginLeft: '5px', 
                cursor: 'pointer',
                fontWeight: 'bold'
              }}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      
      <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
        <input
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && handleAddTag()}
          placeholder="添加标签"
          style={{ flex: 1, padding: '5px' }}
        />
        <button onClick={handleAddTag} style={{ padding: '5px 10px' }}>添加</button>
      </div>
      
      <div style={{ display: 'flex', gap: '10px', marginBottom: '10px', alignItems: 'center' }}>
        <label>模型: </label>
        <select 
          value={selectedModel} 
          onChange={(e) => setSelectedModel(e.target.value)}
          style={{ padding: '5px' }}
        >
          {availableModels.map((model: any) => (
            <option key={model.id} value={model.id}>{model.name}</option>
          ))}
        </select>
        <button onClick={handleAutoGenerate} style={{ padding: '5px 10px' }}>自动生成</button>
      </div>
      
      <button onClick={handleSave} style={{ padding: '5px 15px', background: '#4caf50', color: 'white', border: 'none', borderRadius: '4px' }}>保存标签</button>
    </div>
  );
};

// 在文件列表中添加标签管理功能
const Files = () => {
    const { t } = useTranslation('knowledge')
    const { id } = useParams()

    const { isEditable, setEditable } = useKnowledgeStore();
    const { page, pageSize, data: datalist, total, loading, setPage, search, reload, filterData } = useTable({ cancelLoadingWhenReload: true }, (param) =>
        readFileByLibDatabase({ ...param, id, name: param.keyword }).then(res => {
            setEditable(res.writeable)
            return res
        })
    )
    
    // 添加标签更新处理函数
    const handleTagsUpdate = (fileId: number, newTags: string[]) => {
        // 更新文件列表中的标签
        setPagination(prev => ({
            ...prev,
            data: prev.data.map(file => 
                file.id === fileId ? { ...file, tags: newTags.join(',') } : file
            )
        }));
    };
    
    // 修改渲染文件项的函数
    const renderFileItem = (file: any) => (
        <div key={file.id} className="file-item" style={{ padding: '15px', borderBottom: '1px solid #eee' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>{file.file_name}</span>
                {/* 保留原有的操作按钮 */}
                <div style={{ display: 'flex', gap: '10px' }}>
                    <Button variant="link" disabled={file.status !== 2} className="px-2 dark:disabled:opacity-80" onClick={() => onPreview(file.id)}>{t('view')}</Button>
                    <Button variant="link" className="px-2" onClick={() => handleDownload(file.id, file.file_name)}>{t('download')}</Button>
                    {isEditable ?
                        <Button variant="link" onClick={() => handleDelete(file.id)} className="text-red-500 px-2">{t('delete')}</Button> :
                        <Button variant="link" className="ml-4 text-gray-400 px-2">{t('delete')}</Button>
                    }
                </div>
            </div>
            
            {/* 标签管理组件 */}
            <TagInput 
                fileId={file.id}
                tags={file.tags ? file.tags.split(',') : []} 
                onTagsUpdate={handleTagsUpdate}
                availableModels={availableModels}
            />
        </div>
    );
    // 解析中 轮巡
    const timerRef = useRef(null)
    useEffect(() => {
        if (datalist.some(el => el.status === 1)) {
            timerRef.current = setTimeout(() => {
                reload()
            }, 5000)
            return () => clearTimeout(timerRef.current)
        }
    }, [datalist])

    // filter
    const [filter, setFilter] = useState(999)
    useEffect(() => {
        filterData({ status: filter })
    }, [filter])


    const handleDelete = (id) => {
        bsConfirm({
            title: t('prompt'),
            desc: t('confirmDeleteFile'),
            onOk(next) {
                captureAndAlertRequestErrorHoc(deleteFile(id).then(res => {
                    reload()
                }))
                next()
            },
        })
    }

    const selectChange = (id) => {
        setFilter(Number(id))
    }

    // 重试解析
    const handleRetry = (objs) => {
        captureAndAlertRequestErrorHoc(retryKnowledgeFileApi({ file_objs: objs }).then(res => {
            reload()
        }))
    }

    // 导出文件信息
    const handleExport = async () => {
        try {
            const blob = await exportKnowledgeFileApi(Number(id));
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `knowledge_files_${id}.csv`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('导出失败:', error);
        }
    };

    const handleVectorExport = async () => {
        try {
            const blob = await exportKnowledgeVectorApi(Number(id));
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `knowledge_vectors_${id}.csv`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        } catch (error) {
            console.error('导出向量数据失败:', error);
            message({ variant: 'error', description: '导出向量数据失败' });
        }
    };

    const handleVectorImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        
        try {
            await importKnowledgeVectorApi(Number(id), file);
            message({ variant: 'success', description: '导入向量数据成功' });
            // 导入成功后刷新页面
            setPage(1);
            setFilter(999);
        } catch (error) {
            console.error('导入向量数据失败:', error);
            message({ variant: 'error', description: '导入向量数据失败' });
        } finally {
            // 重置文件输入框
            if (e.target) {
                e.target.value = '';
            }
        }
    };

    // 策略解析
    const dataSouce = useMemo(() => {
        return datalist.map(el => {
            if (!el.split_rule) return {
                ...el,
                strategy: ['', '']
            }
            const rule = JSON.parse(el.split_rule)
            const { separator, separator_rule } = rule
            const data = separator.map((el, i) => `${separator_rule[i] === 'before' ? '✂️' : ''}${el}${separator_rule[i] === 'after' ? '✂️' : ''}`)
            return {
                ...el,
                strategy: [data.length > 2 ? data.slice(0, 2).join(',') : '', data.join(',')]
            }
        })
    }, [datalist])

    const splitRuleDesc = (el) => {
        if (!el.split_rule) return el.strategy[1].replace(/\n/g, '\\n') // 兼容历史数据
        const suffix = el.file_name.split('.').pop().toUpperCase()
        const excel_rule = JSON.parse(el.split_rule).excel_rule
        if (!excel_rule) return el.strategy[1].replace(/\n/g, '\\n') // 兼容历史数据
        return ['XLSX', 'XLS', 'CSV'].includes(suffix) ? `每 ${excel_rule.slice_length} 行作为一个分段` : el.strategy[1].replace(/\n/g, '\\n')
    }

    const [availableModels, setAvailableModels] = useState([]);
    const [files, setFiles] = useState([]);
  
  useEffect(() => {
    // 获取可用模型列表
    const fetchModels = async () => {
      try {
        const response = await fetch('/api/v1/knowledge/models');
        const result = await response.json();
        setAvailableModels(result.models);
      } catch (error) {
        console.error('Failed to fetch models:', error);
      }
    };
    
    fetchModels();
  }, []);
  
  // 添加标签更新处理函数
  const handleTagsUpdate = (fileId: number, newTags: string[]) => {
    // 更新文件列表中的标签
    setFiles(prevFiles => 
      prevFiles.map(file => 
        file.id === fileId ? { ...file, tags: newTags.join(',') } : file
      )
    );
  };
  
  const handleTagsUpdate = (fileId, newTags) => {
    // 更新文件列表中的标签
    setFiles(prevFiles => 
      prevFiles.map(file => 
        file.id === fileId ? { ...file, tags: newTags.join(',') } : file
      )
    );
  };
  
  const renderFileItem = (file) => (
    <div key={file.id} className="file-item">
      <span>{file.file_name}</span>
      <TagInput 
        fileId={file.id}
        tags={file.tags ? file.tags.split(',') : []} 
        onTagsUpdate={handleTagsUpdate}
        availableModels={availableModels}
      />
      <Button variant="link" disabled={file.status !== 2} className="px-2 dark:disabled:opacity-80" onClick={() => onPreview(file.id)}>{t('view')}</Button>
      <Button variant="link" className="px-2" onClick={() => handleDownload(file.id, file.file_name)}>{t('download')}</Button>
      {isEditable ?
          <Button variant="link" onClick={() => handleDelete(file.id)} className="text-red-500 px-2">{t('delete')}</Button> :
          <Button variant="link" className="ml-4 text-gray-400 px-2">{t('delete')}</Button>
        }
      </div>
    );

    return <div className="relative">
        {loading && <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
            <LoadingIcon />
        </div>}
        <div className="absolute right-0 top-[-62px] flex gap-4 items-center">
            <SearchInput placeholder={t('searchFileName')} onChange={(e) => search(e.target.value)}></SearchInput>
            {isEditable && (
                <>
                    <Button variant="outline" className="flex items-center" onClick={handleExport}>
                        <Download size={16} className="mr-1" />
                        {t('export')}
                    </Button>
                    <Button variant="outline" className="flex items-center" onClick={handleVectorExport}>
                        <Download size={16} className="mr-1" />
                        导出向量
                    </Button>
                    <label className="flex items-center cursor-pointer">
                        <Button variant="outline" className="flex items-center" asChild>
                            <span>
                                <Upload size={16} className="mr-1" />
                                导入向量
                            </span>
                        </Button>
                        <input 
                            type="file" 
                            accept=".csv" 
                            className="hidden" 
                            onChange={handleVectorImport}
                        />
                    </label>
                </>
            )}
            {isEditable && <Link to={`/filelib/upload/${id}`}><Button className="px-8" onClick={() => { }}>{t('uploadFile')}</Button></Link>}
        </div>
        <div className="h-[calc(100vh-144px)] overflow-y-auto pb-20">
            <div className="file-list">
                {dataSouce.map(el => renderFileItem(el))}
            </div>
        </div>
        <div className="bisheng-table-footer px-6">
            <p></p>
            <div>
                <AutoPagination
                    page={page}
                    pageSize={pageSize}
                    total={total}
                    onChange={(newPage) => setPage(newPage)}
                />
            </div>
        </div>
    </div>

};