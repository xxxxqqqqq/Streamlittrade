import {flushPromises,mount} from '@vue/test-utils'
import {createMemoryHistory,createRouter} from 'vue-router'
import {beforeEach,describe,expect,it,vi} from 'vitest'

vi.mock('../api',()=>({api:{get:vi.fn(),post:vi.fn(),patch:vi.fn()}}))

import {api} from '../api'
import ModelDetail from './ModelDetail.vue'

// 模型详情页只多认一件事：训练留下 grid_search 时才出现网格搜索卡，
// 并且高亮行必须跟着后端登记的 selected 参数，而不是页面自己猜的最大值。
const stub={template:'<div/>'}
const LEARNING_RATES=[0.03,0.05,0.1],LEAF_NODES=[15,31,63]
const candidates=LEARNING_RATES.flatMap(learning_rate=>LEAF_NODES.map(max_leaf_nodes=>({
  parameters:{max_iter:200,max_depth:5,learning_rate,max_leaf_nodes},
  fold_rank_ics:[0.010,0.012,0.014],
  rank_ic:Number((0.008+learning_rate+max_leaf_nodes/1000).toFixed(6)),
})))
const gridSearch={
  kind:'hgb_learning_rate_leaf_nodes_grid_v2',
  selection_metric:'tuning_folds_mean_rank_ic',
  selection_folds:[
    {fold:1,test_start:'2022-07-01',test_end:'2022-10-31'},
    {fold:2,test_start:'2022-11-01',test_end:'2023-02-28'},
    {fold:3,test_start:'2023-03-01',test_end:'2023-06-30'},
  ],
  grid:{learning_rate:LEARNING_RATES,max_leaf_nodes:LEAF_NODES},
  candidates,
  // 故意不选均值最高的那组：页面必须按登记结果高亮（第 4 组）。
  selected:{parameters:candidates[4].parameters,rank_ic:candidates[4].rank_ic},
}
function modelPayload(grid?:any){
  return {
    id:'m1',name:'模型A',algorithm:'hist_gradient_boosting',version:1,stage:'candidate',
    artifact_uri:'s3://model',prediction_artifact_uri:'s3://prediction',created_at:'2026-09-22T09:00:00Z',
    metrics:{roc_auc:0.56,rank_ic:0.041,rank_ic_decay:0.002,evaluation_scope:'tuning_oos',folds:[],research_split:{training:{start:'2019-01-01',end:'2022-06-30'},tuning:{start:'2022-07-01',end:'2023-06-30'}}},
    reproducibility:{
      features:['volatility_20d','turnover_20d'],model_sha256:'a'.repeat(64),python_version:'3.12.0',sklearn_version:'1.5.0',
      dataset:{name:'数据集A',horizon:5,label_mode:'executable_open_to_open_cross_sectional_v1'},
      ...(grid?{grid_search:grid}:{}),
    },
  }
}
async function mountDetail(grid?:any){
  ;(api.get as any).mockImplementation((url:string)=>{
    if(url==='/models/m1/detail')return Promise.resolve({data:modelPayload(grid)})
    if(url==='/models/m1/sealed-evaluation')return Promise.resolve({data:null})
    return Promise.reject(new Error(`未预置的接口 ${url}`))
  })
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/models/:id',component:stub},{path:'/:pathMatch(.*)*',component:stub}]})
  await router.push('/models/m1')
  await router.isReady()
  const wrapper=mount(ModelDetail,{global:{plugins:[router]}})
  await flushPromises()
  return wrapper
}

describe('模型详情的网格搜索留档',()=>{
  beforeEach(()=>vi.clearAllMocks())

  it('渲染选中参数、候选表和推荐口径',async()=>{
    const wrapper=await mountDetail(gridSearch)
    const panel=wrapper.find('.grid-search-panel')
    expect(panel.exists()).toBe(true)
    expect(panel.text()).toContain('按全部调参折的 OOS RankIC 均值选优')
    expect(panel.text()).toContain('learning_rate = 0.05')
    expect(panel.text()).toContain('max_leaf_nodes = 31')
    expect(panel.text()).toContain('learning_rate')
    expect(panel.text()).toContain('max_leaf_nodes')
    expect(panel.text()).toContain('第 3 折')
    // 表头 + 9 组候选
    expect(panel.findAll('.grid-search-row')).toHaveLength(10)
    // 2 个参数列 + 3 个折 + 均值 + 判断，表头与数据行逐列对齐
    expect(panel.findAll('.grid-search-row.head span')).toHaveLength(7)
    const firstRow=panel.findAll('.grid-search-row')[1]
    expect(firstRow.element.children).toHaveLength(7)
    expect(firstRow.attributes('style')).toContain('grid-template-columns')
    expect(panel.text()).toContain('0.0100')
    expect(panel.text()).toContain('共比较 9 组参数 · 3 折调参')
    wrapper.unmount()
  })

  it('高亮后端登记的那一组参数',async()=>{
    const wrapper=await mountDetail(gridSearch)
    const selected=wrapper.findAll('.grid-search-row.selected')
    expect(selected).toHaveLength(1)
    expect(selected[0].text()).toContain('0.05')
    expect(selected[0].text()).toContain('31')
    expect(selected[0].text()).not.toContain('63')
    expect(selected[0].text()).toContain('已选')
    expect(selected[0].text()).toContain('有效')
    wrapper.unmount()
  })

  it('后端没登记选中参数时退化成均值最高的一组',async()=>{
    const wrapper=await mountDetail({...gridSearch,selected:undefined})
    const selected=wrapper.findAll('.grid-search-row.selected')
    expect(selected).toHaveLength(1)
    expect(selected[0].text()).toContain('0.1')
    expect(selected[0].text()).toContain('63')
    wrapper.unmount()
  })

  it('没有网格搜索的模型不出现这张卡',async()=>{
    const wrapper=await mountDetail()
    expect(wrapper.find('.grid-search-panel').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('网格搜索')
    wrapper.unmount()
  })

  it('把数据集登记的标签口径摊开给用户看',async()=>{
    const wrapper=await mountDetail()
    expect(wrapper.find('.brief-ranges').text()).toContain('标签口径：次日开盘买入的可执行收益 × 截面相对（跑赢当日中位数）')
    wrapper.unmount()
  })
})
