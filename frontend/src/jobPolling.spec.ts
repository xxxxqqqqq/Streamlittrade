import {describe,expect,it,vi} from 'vitest'
import {pollJobUntilTerminal} from './jobPolling'

describe('pollJobUntilTerminal',()=>{
  it('keeps polling long jobs until the server reports a terminal state',async()=>{
    const states=['queued','running','running','succeeded']
    const onUpdate=vi.fn()
    const onLongRunning=vi.fn()
    const result=await pollJobUntilTerminal(
      async()=>({status:states.shift()||'succeeded'}),
      {intervalMs:1000,longRunningAfterMs:1000,onUpdate,onLongRunning,sleep:async()=>{}},
    )
    expect(result.status).toBe('succeeded')
    expect(onUpdate).toHaveBeenCalledTimes(4)
    expect(onLongRunning).toHaveBeenCalledTimes(1)
  })

  it('returns canceled as a terminal state',async()=>{
    const result=await pollJobUntilTerminal(async()=>({status:'canceled'}),{sleep:async()=>{}})
    expect(result.status).toBe('canceled')
  })

  it('recovers from a transient refresh error',async()=>{
    let attempt=0
    const result=await pollJobUntilTerminal(async()=>{
      attempt+=1
      if(attempt===1)throw new Error('temporary network error')
      return {status:'succeeded'}
    },{intervalMs:1,sleep:async()=>{}})
    expect(result.status).toBe('succeeded')
  })

  it('does not misreport repeated refresh failures as a compute timeout',async()=>{
    await expect(pollJobUntilTerminal(
      async()=>{throw new Error('offline')},
      {intervalMs:1,maxConsecutiveErrors:2,sleep:async()=>{}},
    )).rejects.toThrow('任务仍可能在后台运行')
  })
})
