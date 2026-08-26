import {mount} from '@vue/test-utils'
import {describe,expect,it} from 'vitest'
import DataJobProgress from './DataJobProgress.vue'

const options={global:{stubs:{RouterLink:{template:'<a><slot/></a>'}}}}

describe('DataJobProgress',()=>{
  it('shows real materialization progress and its current stage',()=>{
    const wrapper=mount(DataJobProgress,{
      props:{operation:'materialize',status:'running',progress:46.4,workerName:'local-rtx3060'},
      ...options,
    })
    const bar=wrapper.get('[role="progressbar"]')
    expect(bar.attributes('aria-valuenow')).toBe('46')
    expect(bar.get('i').attributes('style')).toContain('width: 46%')
    expect(wrapper.text()).toContain('正在按股票分区计算所选因子')
    expect(wrapper.text()).toContain('local-rtx3060')
  })

  it('explains queued work without inventing progress',()=>{
    const wrapper=mount(DataJobProgress,{
      props:{operation:'sync',status:'queued',progress:0},
      ...options,
    })
    expect(wrapper.text()).toContain('等待计算节点接单')
    expect(wrapper.text()).toContain('0%')
  })
})
