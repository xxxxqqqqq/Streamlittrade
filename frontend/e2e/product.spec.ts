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

test('top bar carries the five-stage research flow',async({page})=>{
  // 侧栏已经删除：一级导航只有顶栏的五段流，研究首页不参与段高亮。
  await expect(page.locator('aside')).toHaveCount(0)
  const topbar=page.locator('header.topbar')
  for(const label of ['获取数据','因子','训练','回测','模拟盘']){
    await expect(topbar.getByRole('link',{name:label,exact:true})).toBeVisible()
  }
  await expect(topbar.locator('.nav-pill.active')).toHaveCount(0)

  await topbar.getByRole('link',{name:'训练',exact:true}).click()
  await expect(page).toHaveURL(/\/experiments$/)
  await expect(topbar.getByRole('link',{name:'训练',exact:true})).toHaveClass(/active/)
})

test('section tabs replace the sidebar sub-entries',async({page})=>{
  const topbar=page.locator('header.topbar')
  await topbar.getByRole('link',{name:'训练',exact:true}).click()
  const tabs=page.locator('.section-tabs')
  for(const label of ['训练实验','研究数据集','模型仓库','模型比较']){
    await expect(tabs.getByRole('link',{name:label,exact:true})).toBeVisible()
  }
  await tabs.getByRole('link',{name:'模型比较',exact:true}).click()
  await expect(page).toHaveURL(/\/models\/compare$/)
  await expect(page.locator('.section-tab.active')).toHaveText('模型比较')

  // 回测段把策略版本和批量预测收进页签，不再放回侧栏。
  await page.locator('header.topbar').getByRole('link',{name:'回测',exact:true}).click()
  for(const label of ['回测中心','策略版本','批量预测']){
    await expect(page.locator('.section-tabs').getByRole('link',{name:label,exact:true})).toBeVisible()
  }
})

test('dashboard console shows the five-stage status, one next step and what needs attention',async({page})=>{
  // 首页是控制台：五段状态条 + 唯一一个下一步 + 最近动态/需要关注两块事实。
  await expect(page.locator('.next-step')).toContainText('下一步建议')
  await expect(page.getByRole('heading',{name:'最近动态'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'需要关注'})).toBeVisible()
  const stages=page.locator('.stages .stage')
  await expect(stages).toHaveCount(5)
  for(const label of ['获取数据','因子','训练','回测','模拟盘']){
    await expect(page.locator('.stages').getByText(label,{exact:true})).toBeVisible()
  }
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

test('admin governance pages and data details are reachable',async({page})=>{
  // 平台治理从顶栏用户菜单进入，非管理员看不到这几个入口。
  await expect(page.getByRole('link',{name:'用户管理'})).toHaveCount(0)
  await page.getByRole('button',{name:'用户菜单'}).click()
  await expect(page.getByText('平台治理')).toBeVisible()
  await page.getByRole('link',{name:'用户管理'}).click()
  await expect(page.getByRole('heading',{name:'用户管理',level:2})).toBeVisible()
  await expect(page.getByText('admin@quant.local')).toBeVisible()

  await page.locator('header.topbar').getByRole('link',{name:'获取数据',exact:true}).click()
  await expect(page.getByText('数据版本与质量')).toBeVisible()
  // 因子快照是数据段内的页签，用 query 定位到页内快照区，版本详情路由保持不变。
  await page.locator('.section-tabs').getByRole('link',{name:'因子快照',exact:true}).click()
  await expect(page).toHaveURL(/focus=snapshots/)
  await page.locator('.product-link-row').first().click()
  await expect(page.getByText('数据质量详情',{exact:true})).toBeVisible()
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
