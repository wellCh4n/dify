import type { NodeDefault } from '../../types'
import type { TryStartNodeType } from './types'
import { genNodeMetaData } from '@/app/components/workflow/utils'
import { BlockEnum } from '@/app/components/workflow/types'

const metaData = genNodeMetaData({
  sort: -1,
  type: BlockEnum.TryStart,
})
const nodeDefault: NodeDefault<TryStartNodeType> = {
  metaData,
  defaultValue: {},
  checkValid() {
    return {
      isValid: true,
    }
  },
}

export default nodeDefault
