import {flushPromises,mount} from '@vue/test-utils'
import {createMemoryHistory,createRouter} from 'vue-router'
import {beforeEach,describe,expect,it,vi} from 'vitest'

vi.mock('../api',()=>({api:{get:vi.fn(),post:vi.fn()}}))

import {api} from '../api'
import Records from './Records.vue'

// 数据集列表只在后端把 metadata_snapshot 带回来时才显示标签口径；
// 老数据集没有这一项，就整行不显示，不占版面也不露裸英文。
const stub={template:'<div/>'}
const rows=[
  {id:'d1',name:'数据集A',status:'ready',row_count:229000,created_at:'2026-09-22T08:40:00Z',metadata_snapshot:{label_mode:'executable_open_to_open_cross_sectional_v1'}},
  {id:'d2',name:'数据集B',status:'ready',row_count:1200,created_at:'2026-09-21T08:40:00Z',metadata_snapshot:null},
]
async function mountDatasets(){
  ;(api.get as any).mockImplementation((url:string)=>url==='/datasets'?Promise.resolve({data:rows}):Promise.reject(new Error(`未预置的接口 ${url}`)))
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/datasets',component:stub},{path:'/:pathMatch(.*)*',component:stub}]})
  await router.push('/datasets')
  await router.isReady()
  const wrapper=mount(Records,{props:{kind:'datasets'},global:{plugins:[router]}})
  await flushPromises()
  return wrapper
}

describe('数据集列表的标签口径',()=>{
  beforeEach(()=>vi.clearAllMocks())

  it('metadata_snapshot 带标签口径时翻成人话显示',async()=>{
    const wrapper=await mountDatasets()
    const names=wrapper.findAll('.dataset-name')
    expect(names).toHaveLength(2)
    expect(names[0].text()).toContain('数据集A')
    expect(names[0].text()).toContain('标签口径：次日开盘买入的可执行收益 × 截面相对（跑赢当日中位数）')
    expect(names[1].text()).toBe('数据集B')
    wrapper.unmount()
  })
})
