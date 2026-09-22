import {mount} from '@vue/test-utils'
import {createMemoryHistory,createRouter} from 'vue-router'
import {afterEach,beforeEach,describe,expect,it} from 'vitest'
import App from './App.vue'
import {clearSession} from './auth'
import {clearProject} from './projects'

// 顶栏外壳是布局重做的落点：这里就地验证“有五段流、没有侧栏”，
// 不需要启动整个平台。
const stub={template:'<div/>'}
function shellRouter(){
  const routes=[...['/','/data-center','/factor-research','/experiments','/backtests','/paper','/jobs','/models','/models/compare'].map(path=>({path,component:stub})),{path:'/:pathMatch(.*)*',component:stub}]
  return createRouter({history:createMemoryHistory(),routes})
}
async function mountShell(path:string){
  const router=shellRouter()
  await router.push(path)
  await router.isReady()
  const wrapper=mount(App,{global:{plugins:[router]}})
  return wrapper
}

describe('顶栏外壳',()=>{
  beforeEach(()=>{clearSession();clearProject()})
  afterEach(()=>{clearSession();clearProject()})

  it('renders the five-stage flow without a sidebar',async()=>{
    const wrapper=await mountShell('/data-center')
    expect(wrapper.find('aside').exists()).toBe(false)
    const pills=wrapper.findAll('.nav-pill')
    expect(pills.map(pill=>pill.text())).toEqual(['获取数据','因子','训练','回测','模拟盘'])
    expect(pills.filter(pill=>pill.classes().includes('active')).map(pill=>pill.text())).toEqual(['获取数据'])
    wrapper.unmount()
  })

  it('highlights the segment that owns the current route',async()=>{
    const wrapper=await mountShell('/models/compare')
    expect(wrapper.find('.nav-pill.active').text()).toBe('训练')
    wrapper.unmount()
  })

  it('leaves the dashboard without a segment highlight',async()=>{
    const wrapper=await mountShell('/')
    expect(wrapper.findAll('.nav-pill.active')).toHaveLength(0)
    wrapper.unmount()
  })

  it('keeps the task center entry and hides governance links from regular users',async()=>{
    const wrapper=await mountShell('/jobs')
    expect(wrapper.get('a[aria-label="任务中心"]').attributes('href')).toBe('/jobs')
    expect(wrapper.text()).not.toContain('平台治理')
    wrapper.unmount()
  })
})
