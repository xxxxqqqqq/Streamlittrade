import {expect,test} from '@playwright/test'

test.beforeEach(async({page})=>{
  await page.goto('/login')
  await page.getByLabel('邮箱').fill('admin@quant.local')
  await page.getByLabel('密码').fill('quant-dev-admin')
  await page.getByRole('button',{name:'安全登录'}).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('QuantForge')).toBeVisible()
})

test('core research workflow is prominent and secondary analysis is isolated',async({page})=>{
  const sidebar=page.locator('aside')
  await expect(sidebar.getByRole('link',{name:/^1\s+数据与标的$/})).toBeVisible()
  await expect(sidebar.getByRole('link',{name:/^2\s+因子工程$/})).toBeVisible()
  await expect(sidebar.getByRole('link',{name:/^3\s+研究数据集$/})).toBeVisible()
  await expect(sidebar.getByRole('link',{name:/^4\s+模型研究$/})).toBeVisible()
  await expect(sidebar.getByRole('link',{name:/^5\s+模型交易工作台$/})).toBeVisible()
  await expect(sidebar.getByRole('link',{name:/^6\s+组合回测$/})).toBeVisible()
  await expect(page.locator('.core-flow .flow-card')).toHaveCount(6)
  await expect(page.getByText('从研究数据到可交易组合，沿五个阶段推进')).toBeVisible()

  await expect(page.getByRole('link',{name:'模型比较',exact:true})).not.toBeVisible()
  await page.getByRole('button',{name:'研究资产与分析'}).click()
  await expect(page.getByRole('link',{name:'模型比较',exact:true})).toBeVisible()
})

test('global search and notification controls are functional',async({page})=>{
  await page.getByRole('button',{name:'搜索'}).click()
  const search=page.getByPlaceholder('搜索策略、数据、实验、模型或回测')
  await expect(search).toBeVisible()
  // 搜索接口允许当前项目没有任何研究资产，因此用空结果提示验证请求已完成，
  // 避免测试依赖预置的 phase3 演示数据。
  await search.fill('不存在的研究资源987654')
  await expect(page.getByText('没有找到匹配资源。')).toBeVisible()
  await page.keyboard.press('Escape')

  await page.getByRole('button',{name:'通知'}).click()
  await expect(page.getByText('最新通知')).toBeVisible()
  await expect(page.getByText('查看全部通知')).toBeVisible()
})

test('admin product pages and data details are reachable',async({page})=>{
  await expect(page.getByRole('link',{name:'用户管理'})).not.toBeVisible()
  await page.getByRole('button',{name:'平台治理'}).click()
  await page.getByRole('link',{name:'用户管理'}).click()
  await expect(page.getByRole('heading',{name:'用户管理',level:2})).toBeVisible()
  await expect(page.getByText('admin@quant.local')).toBeVisible()

  await page.getByRole('link',{name:/1\s+数据与标的/}).click()
  await expect(page.getByText('数据版本与质量')).toBeVisible()
  await page.locator('.product-link-row').first().click()
  await expect(page.getByRole('heading',{name:'数据质量详情'})).toBeVisible()
})

test('model OOS portfolio backtest can be configured',async({page})=>{
  await page.goto('/backtests/new')
  await page.locator('.form-card select').first().selectOption('model_oos')
  await expect(page.getByRole('heading',{name:'创建模型组合回测'})).toBeVisible()
  await expect(page.getByText('已登记模型')).toBeVisible()
  await expect(page.getByText('Top-N 持仓数量')).toBeVisible()
  await expect(page.getByText('最低入选概率')).toBeVisible()
  await expect(page.getByText('调仓频率（交易日）')).toBeVisible()
})
