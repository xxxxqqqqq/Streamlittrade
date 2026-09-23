import {flushPromises,mount} from '@vue/test-utils'
import {createMemoryHistory,createRouter} from 'vue-router'
import {beforeEach,describe,expect,it,vi} from 'vitest'

vi.mock('../api',()=>({api:{get:vi.fn(),post:vi.fn()}}))

import {api} from '../api'
import Dashboard from './Dashboard.vue'

// 控制台是状态驱动页面，这里用假数据钉住三条事实：五段状态条能反映产物、
// 只给一个下一步、单个接口失败不影响其他区块。
const stub={template:'<div/>'}
const payload:Record<string,any>={
  '/data-center/versions':[{id:'v1',layer:'standardized',status:'ready',row_count:29120,created_at:'2026-09-22T07:00:00Z',specification:{name:'全流程测试数据',start_date:'2019-01-01',end_date:'2024-12-31'}}],
  '/data-center/materializations':[{id:'s1',name:'因子快照A',status:'ready',row_count:229000,created_at:'2026-09-22T08:00:00Z'}],
  '/data-center/factor-research':[{id:'f1',name:'因子检验A',status:'succeeded',created_at:'2026-09-22T08:30:00Z',selected_feature_slugs:['volatility_20d','bm'],metrics:{factors:{volatility_20d:{rank_ic_mean:0.056},turnover_20d:{rank_ic_mean:0.018}}}}],
  '/datasets':[{id:'d1',name:'数据集A',status:'ready',created_at:'2026-09-22T08:40:00Z'}],
  '/experiments':[{id:'e1',name:'实验A',status:'succeeded',created_at:'2026-09-22T08:50:00Z'}],
  '/models':[{id:'m1',name:'模型A',algorithm:'hist_gradient_boosting',stage:'candidate',created_at:'2026-09-22T09:00:00Z',metrics:{roc_auc:0.509}}],
  '/backtests':[{id:'b1',name:'回测A',strategy_name:'model_probability',signal_source:'model_oos',created_at:'2026-09-22T09:05:00Z',start_date:'2022-08-01',end_date:'2023-10-31',metrics:{excess_return:-3.81,turnover_events:57}}],
  '/jobs':[],
  '/paper/accounts':[],
}

function respond(overrides:Record<string,any>={}){
  const data={...payload,...overrides}
  ;(api.get as any).mockImplementation((url:string)=>url in data?Promise.resolve({data:data[url]}):Promise.reject(new Error(`未预置的接口 ${url}`)))
}
async function mountConsole(){
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:stub}]})
  await router.push('/')
  await router.isReady()
  const wrapper=mount(Dashboard,{global:{plugins:[router]}})
  await flushPromises()
  return wrapper
}

describe('研究控制台首页',()=>{
  beforeEach(()=>{vi.clearAllMocks();respond()})

  it('renders the five-stage status bar from the newest products',async()=>{
    const wrapper=await mountConsole()
    const stages=wrapper.findAll('.stage')
    expect(stages).toHaveLength(5)
    expect(stages.map(stage=>stage.text()).join(' ')).toContain('获取数据')
    expect(wrapper.find('.stage').text()).toContain('全流程测试数据')
    expect(wrapper.text()).toContain('2 个有效')
    expect(wrapper.text()).toContain('— 小幅跑输')
    // 没有模拟盘账户时给中性“待配置”，不是错误也不是空徽标。
    expect(wrapper.text()).toContain('待配置')
    wrapper.unmount()
  })

  it('recommends exactly one next action with the reason',async()=>{
    const wrapper=await mountConsole()
    const next=wrapper.findAll('.next-step')
    expect(next).toHaveLength(1)
    expect(next[0].text()).toContain('先解决信号偏弱')
    expect(next[0].find('a').attributes('href')).toBe('/factor-research')
    wrapper.unmount()
  })

  it('shows failed jobs with the reason and a retry action',async()=>{
    respond({'/jobs':[{id:'j1',kind:'training',status:'failed',progress:60,created_at:'2026-09-22T09:10:00Z',error_message:'训练样本不足，无法完成调参'}]})
    const wrapper=await mountConsole()
    const attention=wrapper.findAll('article.panel')[1]
    expect(attention.text()).toContain('模型训练失败')
    expect(attention.text()).toContain('训练样本不足，无法完成调参')
    await attention.find('button.text-button').trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/jobs/j1/retry')
    wrapper.unmount()
  })

  it('loads the remaining blocks when one endpoint fails',async()=>{
    ;(api.get as any).mockImplementation((url:string)=>url==='/models'?Promise.reject(new Error('模型服务不可用')):Promise.resolve({data:payload[url]}))
    const wrapper=await mountConsole()
    expect(wrapper.find('.error-box').text()).toContain('模型：模型服务不可用')
    expect(wrapper.findAll('.stage')).toHaveLength(5)
    expect(wrapper.find('.stage').text()).toContain('全流程测试数据')
    wrapper.unmount()
  })
})
