import {expect,test} from '@playwright/test'

test.beforeEach(async({page})=>{
  await page.goto('/login')
  await page.getByLabel('邮箱').fill('admin@quant.local')
  await page.getByLabel('密码').fill('quant-dev-admin')
  // 登录页已经简化成单一「登录」按钮，断言要与 Login.vue 保持一致。
  await page.getByRole('button',{name:'登录',exact:true}).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByText('QuantForge',{exact:true})).toBeVisible()
})

test('sidebar groups research objects instead of numbered steps',async({page})=>{
  const sidebar=page.locator('aside')
  // 侧栏不再把流程编成 1/2/3 号步骤，而是按研究对象分区。
  await expect(sidebar.getByRole('link',{name:'研究首页',exact:true})).toBeVisible()
  for(const label of ['数据与因子','数据集与实验','模型','回测与模拟','任务','平台治理']){
    await expect(sidebar.getByRole('button',{name:label,exact:true})).toBeVisible()
  }
  await expect(sidebar.getByRole('link',{name:/^一键研究$/})).toHaveCount(0)
  await expect(sidebar.getByRole('link',{name:/^[1-6]\s/})).toHaveCount(0)

  await sidebar.getByRole('button',{name:'数据与因子',exact:true}).click()
  await expect(sidebar.getByRole('link',{name:'数据与标的',exact:true})).toBeVisible()
  await expect(sidebar.getByRole('link',{name:'因子工程',exact:true})).toBeVisible()

  await sidebar.getByRole('button',{name:'模型',exact:true}).click()
  await expect(sidebar.getByRole('link',{name:'模型仓库',exact:true})).toBeVisible()
  await expect(sidebar.getByRole('link',{name:'模型比较',exact:true})).toBeVisible()

  await sidebar.getByRole('button',{name:'回测与模拟',exact:true}).click()
  await expect(sidebar.getByRole('link',{name:'回测中心',exact:true})).toBeVisible()
  await expect(sidebar.getByRole('link',{name:'模拟交易',exact:true})).toBeVisible()
})

test('dashboard shows the recommended next step and recent products',async({page})=>{
  await expect(page.locator('.next-step')).toBeVisible()
  await expect(page.getByText('下一步',{exact:true})).toBeVisible()
  await expect(page.getByRole('heading',{name:'最近产物'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'数据新鲜度'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'任务状态'})).toBeVisible()
  await expect(page.locator('.core-flow .flow-card')).toHaveCount(0)
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

  await page.getByRole('button',{name:'数据与因子',exact:true}).click()
  await page.getByRole('link',{name:'数据与标的',exact:true}).click()
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
