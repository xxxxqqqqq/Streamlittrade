export interface PollableJob {
  status:string
  error_message?:string|null
  [key:string]:unknown
}

interface PollingOptions<T extends PollableJob> {
  intervalMs?:number
  longRunningAfterMs?:number
  maxConsecutiveErrors?:number
  onUpdate?:(job:T)=>void
  onLongRunning?:()=>void
  sleep?:(milliseconds:number)=>Promise<void>
}

const terminalStatuses=new Set(['succeeded','failed','canceled'])

export async function pollJobUntilTerminal<T extends PollableJob>(
  fetchJob:()=>Promise<T>,
  options:PollingOptions<T>={},
):Promise<T>{
  const intervalMs=options.intervalMs??2000
  const longRunningAfterMs=options.longRunningAfterMs??180000
  const maxConsecutiveErrors=options.maxConsecutiveErrors??5
  const sleep=options.sleep??(milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds)))
  let waitedMs=0
  let consecutiveErrors=0
  let longRunningNotified=false

  while(true){
    try{
      const job=await fetchJob()
      consecutiveErrors=0
      options.onUpdate?.(job)
      if(terminalStatuses.has(job.status))return job
    }catch(error){
      consecutiveErrors+=1
      if(consecutiveErrors>=maxConsecutiveErrors){
        throw new Error('暂时无法刷新任务状态，任务仍可能在后台运行，请到任务中心查看。',{cause:error})
      }
    }

    if(!longRunningNotified&&waitedMs>=longRunningAfterMs){
      longRunningNotified=true
      options.onLongRunning?.()
    }
    await sleep(intervalMs)
    waitedMs+=intervalMs
  }
}
