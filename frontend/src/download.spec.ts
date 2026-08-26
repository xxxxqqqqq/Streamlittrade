import {describe,expect,it,vi} from 'vitest'
import {api} from './api'
import {DOWNLOAD_TIMEOUT_MS,downloadApiFile} from './download'

describe('artifact downloads',()=>{
  it('does not impose an Axios deadline on large Parquet files',async()=>{
    const get=vi.spyOn(api,'get').mockRejectedValueOnce({code:'ECONNABORTED',message:'timeout of 0ms exceeded'})

    await expect(downloadApiFile('/datasets/example/artifact','example.parquet'))
      .rejects.toThrow('下载连接已中断，请检查网络后重试。')
    expect(get).toHaveBeenCalledWith('/datasets/example/artifact',{responseType:'blob',timeout:DOWNLOAD_TIMEOUT_MS})
    get.mockRestore()
  })
})
