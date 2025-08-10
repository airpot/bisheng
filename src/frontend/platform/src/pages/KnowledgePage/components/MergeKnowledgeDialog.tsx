import React, { useState, useEffect } from 'react';
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '../../../components/ui/dialog';
import { Input } from '../../../components/ui/input';
import { Label } from '../../../components/ui/label';
import { RadioGroup, RadioGroupItem } from '../../../components/ui/radio-group';
import { mergeKnowledgeApi } from '../../../controllers/API';
import { message } from 'antd';

interface Knowledge {
  id: number;
  name: string;
}

interface MergeKnowledgeDialogProps {
  knowledges: Knowledge[];
  selectedKnowledges: number[];
  onMergeComplete: () => void;
  children: React.ReactNode;
}

export function MergeKnowledgeDialog({
  knowledges,
  selectedKnowledges,
  onMergeComplete,
  children
}: MergeKnowledgeDialogProps) {
  const [open, setOpen] = useState(false);
  const [targetKnowledgeId, setTargetKnowledgeId] = useState<number | null>(null);
  const [newKnowledgeName, setNewKnowledgeName] = useState('');
  const [duplicateHandler, setDuplicateHandler] = useState('skip');
  const [merging, setMerging] = useState(false);

  useEffect(() => {
    // 如果有选中的知识库，将第一个设为目标知识库
    if (selectedKnowledges.length > 0) {
      setTargetKnowledgeId(selectedKnowledges[0]);
    }
  }, [selectedKnowledges]);

  const handleMerge = async () => {
    if (!targetKnowledgeId) {
      message.error('请选择目标知识库');
      return;
    }

    if (selectedKnowledges.length < 2) {
      message.error('请至少选择两个知识库进行合并');
      return;
    }

    if (!selectedKnowledges.includes(targetKnowledgeId)) {
      message.error('目标知识库必须是选中的知识库之一');
      return;
    }

    const sourceIds = selectedKnowledges.filter(id => id !== targetKnowledgeId);

    try {
      setMerging(true);
      const result = await mergeKnowledgeApi(
        sourceIds,
        targetKnowledgeId,
        newKnowledgeName || undefined,
        duplicateHandler
      );
      
      message.success(result.data?.message || '知识库合并成功');
      setOpen(false);
      onMergeComplete();
    } catch (error: any) {
      console.error('合并失败:', error);
      message.error(error.response?.data?.detail || '合并失败');
    } finally {
      setMerging(false);
    }
  };

  const targetKnowledge = knowledges.find(k => k.id === targetKnowledgeId);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {children}
      </DialogTrigger>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>合并知识库</DialogTitle>
          <DialogDescription>
            将多个知识库合并到目标知识库中。可以选择如何处理重复的文档。
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid grid-cols-4 items-center gap-4">
            <Label htmlFor="target" className="text-right">
              目标知识库
            </Label>
            <div className="col-span-3">
              <select
                id="target"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                value={targetKnowledgeId || ''}
                onChange={(e) => setTargetKnowledgeId(Number(e.target.value))}
              >
                <option value="">请选择目标知识库</option>
                {knowledges
                  .filter(k => selectedKnowledges.includes(k.id))
                  .map(knowledge => (
                    <option key={knowledge.id} value={knowledge.id}>
                      {knowledge.name}
                    </option>
                  ))}
              </select>
            </div>
          </div>
          
          {targetKnowledge && (
            <div className="grid grid-cols-4 items-center gap-4">
              <Label htmlFor="name" className="text-right">
                新名称
              </Label>
              <div className="col-span-3">
                <Input
                  id="name"
                  placeholder={`保持原名 (${targetKnowledge.name})`}
                  value={newKnowledgeName}
                  onChange={(e) => setNewKnowledgeName(e.target.value)}
                />
              </div>
            </div>
          )}
          
          <div className="grid grid-cols-4 items-center gap-4">
            <Label className="text-right">重复处理</Label>
            <div className="col-span-3">
              <RadioGroup value={duplicateHandler} onValueChange={setDuplicateHandler}>
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="skip" id="skip" />
                  <Label htmlFor="skip">跳过重复文档</Label>
                </div>
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="overwrite" id="overwrite" />
                  <Label htmlFor="overwrite">覆盖重复文档</Label>
                </div>
                <div className="flex items-center space-x-2">
                  <RadioGroupItem value="rename" id="rename" />
                  <Label htmlFor="rename">重命名新文档</Label>
                </div>
              </RadioGroup>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            取消
          </Button>
          <Button onClick={handleMerge} disabled={merging}>
            {merging ? '合并中...' : '确认合并'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}