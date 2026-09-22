import {mount} from '@vue/test-utils'
import {describe,expect,it} from 'vitest'
import MetricValue from './MetricValue.vue'

describe('MetricValue',()=>{
  it('scales rate values into percent',()=>{
    expect(mount(MetricValue,{props:{value:0.1234}}).text()).toBe('12.34%')
    expect(mount(MetricValue,{props:{value:-0.05}}).text()).toBe('-5.00%')
    expect(mount(MetricValue,{props:{value:0.685,digits:1}}).text()).toBe('68.5%')
  })

  it('keeps ratios at the requested precision',()=>{
    expect(mount(MetricValue,{props:{value:1.23456,mode:'ratio'}}).text()).toBe('1.235')
    expect(mount(MetricValue,{props:{value:2.3,mode:'ratio',digits:2}}).text()).toBe('2.30')
    expect(mount(MetricValue,{props:{value:12.3,mode:'percent'}}).text()).toBe('12.30%')
  })

  it('shows a dash for missing values and tones only on request',()=>{
    expect(mount(MetricValue,{props:{value:null,tone:true}}).text()).toBe('—')
    expect(mount(MetricValue,{props:{value:null,tone:true}}).classes()).not.toContain('positive')
    expect(mount(MetricValue,{props:{value:0.2,tone:true}}).classes()).toContain('positive')
    expect(mount(MetricValue,{props:{value:-0.2,tone:true}}).classes()).toContain('negative')
    expect(mount(MetricValue,{props:{value:-0.2}}).classes()).not.toContain('negative')
  })
})
