import {flushPromises,mount} from '@vue/test-utils'
import {createMemoryHistory,createRouter} from 'vue-router'
import {beforeEach,describe,expect,it,vi} from 'vitest'

vi.mock('../api',()=>({api:{get:vi.fn(),post:vi.fn()}}))

import {api} from '../api'
import FactorResearch from './FactorResearch.vue'

// 因子检验结果里的去冗余记录要能直接读出"谁和谁重复、最后留了谁"，
// 用户不该再去相关性矩阵里自己对。
const stub={template:'<div/>'}
const run:any={
  id:'r1',name:'因子检验A',status:'succeeded',created_at:'2026-09-22T08:30:00Z',selected_feature_slugs:['skewness_120d'],
  metrics:{
    sample_rows:229000,forward_period:5,date_min:'2019-01-01',date_max:'2022-06-30',full_date_max:'2024-12-31',
    research_protocol:{training_boundary:'2022-06-30'},
    factors:{
      skewness_20d:{passed:false,coverage:0.92,rank_ic_mean:0.052,rank_ic_ir:0.4,rank_ic_p_value:0.02,rank_ic_q_value:0.04,reasons:['与已入选因子 skewness_120d 高度相关'],dedup_dropped_by:'skewness_120d',dedup_abs_correlation:0.86},
      skewness_120d:{passed:true,coverage:0.93,rank_ic_mean:0.061,rank_ic_ir:0.5,rank_ic_p_value:0.01,rank_ic_q_value:0.03,reasons:[]},
    },
    screening:{selected:['skewness_120d'],rejected:['skewness_20d'],dedup:{method:'greedy_abs_spearman_v1',threshold:0.7,dropped:{skewness_20d:'skewness_120d'}}},
  },
}
async function mountResearch(payload:any=run){
  ;(api.get as any).mockImplementation((url:string)=>{
    if(url==='/data-center/materializations')return Promise.resolve({data:[]})
    if(url==='/data-center/factor-research')return Promise.resolve({data:[payload]})
    return Promise.reject(new Error(`未预置的接口 ${url}`))
  })
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/factor-research',component:stub},{path:'/:pathMatch(.*)*',component:stub}]})
  await router.push('/factor-research')
  await router.isReady()
  const wrapper=mount(FactorResearch,{global:{plugins:[router]}})
  await flushPromises()
  return wrapper
}

describe('因子研究的去冗余说明条',()=>{
  beforeEach(()=>vi.clearAllMocks())

  it('列出被合并的因子和挤掉它的因子',async()=>{
    const wrapper=await mountResearch()
    const strip=wrapper.find('.dedup-strip')
    expect(strip.exists()).toBe(true)
    expect(strip.text()).toContain('去冗余合并')
    expect(strip.text()).toContain('skewness_20d 与 skewness_120d 高度相关（|ρ| > 0.7），已并入 skewness_120d')
    wrapper.unmount()
  })

  it('阈值取后端登记值，不在页面写死',async()=>{
    const payload=structuredClone(run)
    payload.metrics.screening.dedup.threshold=0.65
    const wrapper=await mountResearch(payload)
    expect(wrapper.find('.dedup-strip').text()).toContain('|ρ| > 0.65')
    wrapper.unmount()
  })

  it('没有去冗余记录的旧结果不显示说明条',async()=>{
    const payload=structuredClone(run)
    delete (payload.metrics.screening as any).dedup
    const wrapper=await mountResearch(payload)
    expect(wrapper.find('.dedup-strip').exists()).toBe(false)
    wrapper.unmount()
  })

  it('去冗余跑过但没合并任何因子时也说明一句',async()=>{
    const payload=structuredClone(run)
    payload.metrics.screening.dedup.dropped={}
    const wrapper=await mountResearch(payload)
    expect(wrapper.find('.dedup-strip').text()).toContain('本次没有被合并的因子')
    wrapper.unmount()
  })
})
