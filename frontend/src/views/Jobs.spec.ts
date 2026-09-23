import {flushPromises,mount} from '@vue/test-utils'
import {createMemoryHistory,createRouter} from 'vue-router'
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'

vi.mock('../api',()=>({api:{get:vi.fn(),post:vi.fn(),defaults:{baseURL:'/api/v1'}}}))

import {api} from '../api'
import Jobs from './Jobs.vue'

// 任务中心要说人话：类型有中文名、失败原因能展开、完成的任务直达产出物。
class FakeSocket{onopen:any;onmessage:any;onclose:any;onerror:any;close(){}}
const stub={template:'<div/>'}
function jobRows(){
  return [
    {id:'j1',kind:'data_sync',status:'succeeded',progress:100,created_at:'2026-09-22T07:00:00Z',queue_name:'default',worker_name:'worker-1',result_summary:{standard_version_id:'v1',rows:29120}},
    {id:'j2',kind:'training',status:'failed',progress:40,created_at:'2026-09-22T08:00:00Z',error_message:'训练样本不足，无法完成调参'},
  ]
}
async function mountJobs(){
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:stub}]})
  await router.push('/jobs')
  await router.isReady()
  const wrapper=mount(Jobs,{global:{plugins:[router]}})
  await flushPromises()
  return wrapper
}

describe('任务中心',()=>{
  beforeEach(()=>{
    vi.clearAllMocks()
    vi.stubGlobal('WebSocket',FakeSocket)
    ;(api.get as any).mockResolvedValue({data:jobRows()})
    ;(api.post as any).mockResolvedValue({data:{}})
  })
  afterEach(()=>{vi.unstubAllGlobals()})

  it('translates job types and links to the produced artifact',async()=>{
    const wrapper=await mountJobs()
    expect(wrapper.text()).toContain('数据同步')
    expect(wrapper.text()).toContain('获取数据')
    const link=wrapper.findAll('a.text-button').find(item=>item.text().includes('查看数据版本'))
    expect(link?.attributes('href')).toBe('/data-center/versions/v1')
    wrapper.unmount()
  })

  it('keeps the failure reason folded until it is expanded',async()=>{
    const wrapper=await mountJobs()
    const toggle=wrapper.find('.failure-toggle')
    expect(toggle.text()).toContain('训练样本不足，无法完成调参')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(wrapper.find('.failure-toggle').attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.failure-toggle').classes()).toContain('open')
    wrapper.unmount()
  })

  it('retries a failed job and refreshes the list',async()=>{
    const wrapper=await mountJobs()
    const retry=wrapper.findAll('button.text-button').find(item=>item.text().includes('重试'))
    await retry?.trigger('click')
    await flushPromises()
    expect(api.post).toHaveBeenCalledWith('/jobs/j2/retry')
    expect((api.get as any).mock.calls.length).toBeGreaterThan(1)
    wrapper.unmount()
  })
})
