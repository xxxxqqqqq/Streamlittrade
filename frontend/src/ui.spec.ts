import {describe,expect,it} from 'vitest'
import {errorMessage} from './ui'

describe('unified error formatting',()=>{
  it('uses API detail when available',()=>{
    expect(errorMessage({response:{data:{detail:'没有访问权限'}}})).toBe('没有访问权限')
  })

  it('joins validation messages',()=>{
    expect(errorMessage({response:{data:{detail:[{msg:'名称不能为空'},{msg:'日期无效'}]}}})).toBe('名称不能为空；日期无效')
  })
})
