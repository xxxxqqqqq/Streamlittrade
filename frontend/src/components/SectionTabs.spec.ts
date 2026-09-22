import {mount} from '@vue/test-utils'
import {createMemoryHistory,createRouter} from 'vue-router'
import {describe,expect,it} from 'vitest'
import SectionTabs from './SectionTabs.vue'
import {dataTabs} from '../sections'

async function mountAt(path:string,query:Record<string,string>={}){
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div/>'}}]})
  await router.push({path,query})
  await router.isReady()
  return mount(SectionTabs,{props:{tabs:dataTabs},global:{plugins:[router]}})
}

describe('SectionTabs',()=>{
  it('renders each tab as a link',async()=>{
    const wrapper=await mountAt('/data-center')
    expect(wrapper.findAll('a').map(link=>link.text())).toEqual(['数据同步与版本','因子快照'])
  })

  it('highlights the tab matching path and query',async()=>{
    expect((await mountAt('/data-center')).find('.section-tab.active').text()).toBe('数据同步与版本')
    expect((await mountAt('/data-center',{focus:'snapshots'})).find('.section-tab.active').text()).toBe('因子快照')
  })

  it('renders no active tab when the path belongs to another section',async()=>{
    const wrapper=await mountAt('/backtests')
    expect(wrapper.find('.section-tab.active').exists()).toBe(false)
  })
})
