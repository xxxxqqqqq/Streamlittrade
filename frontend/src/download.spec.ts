import {describe,expect,it,vi} from 'vitest'
import {api} from './api'
import {DOWNLOAD_TIMEOUT_MS,downloadApiFile} from './download'

describe('artifact downloads',()=>{
  it('allows a realistic transfer window for large Parquet files',async()=>{
    const get=vi.spyOn(api,'get').mockRejectedValueOnce({code:'ECONNABORTED',message:'timeout of 600000ms exceeded'})

    await expect(downloadApiFile('/datasets/example/artifact','example.parquet'))
      .rejects.toThrow('下载时间较长，请检查网络后重试；大文件下载最长等待 10 分钟。')
    expect(get).toHaveBeenCalledWith('/datasets/example/artifact',{responseType:'blob',timeout:DOWNLOAD_TIMEOUT_MS})
    get.mockRestore()
  })
})
