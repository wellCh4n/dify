import type { FC } from 'react'
import {
  memo,
  useEffect,
  useState,
} from 'react'
import {
  Background,
  useNodesInitialized,
  useViewport,
} from 'reactflow'
import { useTranslation } from 'react-i18next'
import { TryStartNodeDumb } from '../try-start'
import { useNodeTryInteractions } from './use-interactions'
import type { TryNodeType } from './types'
import AddBlock from './add-block'
import cn from '@/utils/classnames'
import type { NodeProps } from '@/app/components/workflow/types'
import Toast from '@/app/components/base/toast'

const i18nPrefix = 'workflow.nodes.iteration'

const Node: FC<NodeProps<TryNodeType>> = ({
  id,
  data,
}) => {
  const { zoom } = useViewport()
  const nodesInitialized = useNodesInitialized()
  const { handleNodeTryRerender } = useNodeTryInteractions()
  const { t } = useTranslation()
  const [showTips, setShowTips] = useState(data._isShowTips)

  useEffect(() => {
    if (nodesInitialized)
      handleNodeTryRerender(id)
    if (data.is_parallel && showTips) {
      Toast.notify({
        type: 'warning',
        message: t(`${i18nPrefix}.answerNodeWarningDesc`),
        duration: 5000,
      })
      setShowTips(false)
    }
  }, [nodesInitialized, id, handleNodeTryRerender, data.is_parallel, showTips, t])

  return (
    <div className={cn(
      'relative h-full min-h-[90px] w-full min-w-[240px] rounded-2xl bg-workflow-canvas-workflow-bg',
    )}>
      <Background
        id={`iteration-background-${id}`}
        className='!z-0 rounded-2xl'
        gap={[14 / zoom, 14 / zoom]}
        size={2 / zoom}
        color='var(--color-workflow-canvas-workflow-dot-color)'
      />
      {
        data._isCandidate && (
          <TryStartNodeDumb />
        )
      }
      {
        data._children!.length === 1 && (
          <AddBlock
            tryNodeId={id}
            tryNodeData={data}
          />
        )
      }
    </div>
  )
}

export default memo(Node)
