import {mount} from '@vue/test-utils'
import {describe,expect,it} from 'vitest'
import {nextTick} from 'vue'
import CandlestickTradeChart from './CandlestickTradeChart.vue'

describe('CandlestickTradeChart',()=>{
  it('renders OOS scores and emits the real trade event',async()=>{
    const wrapper=mount(CandlestickTradeChart,{props:{
      bars:[
        {date:'2024-01-02',open:10,high:11,low:9,close:10.5,volume:1000},
        {date:'2024-01-03',open:10.6,high:12,low:10,close:11.5,volume:1200},
      ],
      signals:[{date:'2024-01-02',probability:.72,rank:1,universe_size:20,selected:true}],
      events:[{date:'2024-01-03',signal_date:'2024-01-02',action:'BUY',price:10.6,shares:100}],
    }})
    expect(wrapper.find('.score-line').exists()).toBe(true)
    await wrapper.find('.event-marker').trigger('click')
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({action:'BUY',signal_date:'2024-01-02'})
  })

  it('zooms around the cursor and exposes the current navigation window',async()=>{
    const bars=Array.from({length:80},(_,index)=>({date:`2024-02-${String(index+1).padStart(2,'0')}`,open:10,high:11,low:9,close:10+(index%5),volume:1000}))
    const wrapper=mount(CandlestickTradeChart,{props:{bars,signals:[],events:[]}})
    const chart=wrapper.find('svg')
    Object.defineProperty(chart.element,'getBoundingClientRect',{value:()=>({left:0,width:1000})})
    expect(chart.attributes('data-window-size')).toBe('80')
    chart.element.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,deltaY:-1,clientX:500}))
    await nextTick()
    expect(Number(chart.attributes('data-window-size'))).toBeLessThan(80)
    expect(Number(chart.attributes('data-window-start'))).toBeGreaterThanOrEqual(0)
  })
})
