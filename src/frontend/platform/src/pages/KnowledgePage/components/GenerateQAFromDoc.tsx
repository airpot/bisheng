import { useState, useEffect } from 'react';
import { Button } from '@/components/bs-ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/bs-ui/dialog';
import { Label } from '@/components/bs-ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/bs-ui/select';
import { Input } from '@/components/bs-ui/input';
import { Textarea } from '@/components/bs-ui/textarea';
import { generateQAFromDocs } from '@/controllers/API';
import { captureAndAlertRequestErrorHoc } from '@/controllers/request';
import { useToast } from '@/components/bs-ui/toast/use-toast';
import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface GenerateQAFromDocProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fileIds: number[];
  onGenerateSuccess: (data: any) => void;
}

const GenerateQAFromDoc = ({ open, onOpenChange, fileIds, onGenerateSuccess }: GenerateQAFromDocProps) => {
  const { t } = useTranslation();
  const { toast } = useToast();
  
  const [models, setModels] = useState<any[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>('');
  const [qaNum, setQaNum] = useState<number>(5);
  const [verifyModel, setVerifyModel] = useState<string>('');
  const [prompt, setPrompt] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);

  // 获取可用模型列表
  useEffect(() => {
    // 模拟获取模型列表，实际应该从API获取
    const fetchModels = async () => {
      try {
        // 这里应该调用获取模型列表的API
        // 暂时使用模拟数据
        const mockModels = [
          { id: 1, name: 'Qwen Turbo' },
          { id: 2, name: 'Qwen Plus' },
          { id: 3, name: 'Qwen Max' },
          { id: 4, name: 'GPT-3.5 Turbo' },
          { id: 5, name: 'GPT-4' }
        ];
        setModels(mockModels);
        if (mockModels.length > 0) {
          setSelectedModel(String(mockModels[1].id)); // 默认选择Qwen Plus
        }
      } catch (error) {
        console.error('获取模型列表失败:', error);
        toast({
          variant: 'error',
          description: '获取模型列表失败'
        });
      }
    };

    if (open) {
      fetchModels();
    }
  }, [open, toast]);

  const handleGenerate = async () => {
    if (!selectedModel) {
      toast({
        variant: 'warning',
        description: '请选择生成QA使用的大模型'
      });
      return;
    }

    setLoading(true);
    try {
      const requestData: any = {
        file_ids: fileIds,
        model_id: parseInt(selectedModel),
        qa_num: qaNum || 5
      };

      if (verifyModel) {
        requestData.verify_model_id = parseInt(verifyModel);
      }

      if (prompt) {
        requestData.prompt = prompt;
      }

      const res = await captureAndAlertRequestErrorHoc(generateQAFromDocs(requestData));
      onGenerateSuccess(res);
      onOpenChange(false);
      toast({
        variant: 'success',
        description: '生成QA成功'
      });
    } catch (error) {
      console.error('生成QA失败:', error);
      toast({
        variant: 'error',
        description: '生成QA失败'
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>从文档生成QA</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>选择生成QA使用的大模型 *</Label>
            <Select value={selectedModel} onValueChange={setSelectedModel}>
              <SelectTrigger>
                <SelectValue placeholder="请选择模型" />
              </SelectTrigger>
              <SelectContent>
                {models.map((model) => (
                  <SelectItem key={model.id} value={String(model.id)}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>生成问题数</Label>
            <Input
              type="number"
              min="1"
              value={qaNum}
              onChange={(e) => setQaNum(parseInt(e.target.value) || 5)}
              placeholder="请输入生成问题数，默认为5"
            />
          </div>

          <div className="space-y-2">
            <Label>选择校验问题答案的大模型</Label>
            <Select value={verifyModel} onValueChange={setVerifyModel}>
              <SelectTrigger>
                <SelectValue placeholder="请选择校验模型（可选）" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="">不使用校验模型</SelectItem>
                {models.map((model) => (
                  <SelectItem key={model.id} value={String(model.id)}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>提示词（可选）</Label>
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="请输入生成QA使用的提示词，留空则使用默认提示词"
              rows={4}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleGenerate} disabled={loading}>
            {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            生成QA
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default GenerateQAFromDoc;