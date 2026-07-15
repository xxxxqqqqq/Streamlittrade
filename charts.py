"""
模块：可视化图表 (charts.py)
功能：净值曲线、K 线图（Highcharts Stock 交互式）、最大回撤曲线等图表渲染
依赖：streamlit, plotly.graph_objects, pandas, json
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import json


# ============================================================
# 图表一：净值曲线（Highcharts 同花顺风格）
# ============================================================

def plot_equity(equity_series, initial_cash=None):
    """
    绘制回测净值曲线 —— Highcharts 同花顺风格
    渐变面积填充 + 初始资金参考线 + 十字光标 + 简洁网格

    Args:
        equity_series: pd.Series，索引为日期，值为每日权益
        initial_cash:  初始资金（用于画参考线），默认取序列第一个值

    Returns:
        str: Highcharts HTML 字符串
    """
    import json as _json

    # 如果未指定初始资金，取序列第一个值
    ref_value = initial_cash if initial_cash else round(float(equity_series.iloc[0]), 2)
    final_value = round(float(equity_series.iloc[-1]), 2)
    is_profit = final_value >= ref_value

    # ---- 检测主题 ----
    try:
        bg_check = st.get_option('theme.backgroundColor')
        is_dark = (bg_check or '') in ('#0e1117', '#0d1117', '#0a0a0a', '#000000')
    except Exception:
        is_dark = True

    if is_dark:
        BG = '#0d1117'
        TEXT = '#94a3b8'
        GRID = '#1e293b'
        CROSSHAIR = '#334155'
        LINE_COLOR = '#60a5fa'     # 蓝线
        FILL_TOP = 'rgba(96,165,250,0.25)'
        FILL_BOTTOM = 'rgba(96,165,250,0.02)'
    else:
        BG = '#ffffff'
        TEXT = '#475569'
        GRID = '#e2e8f0'
        CROSSHAIR = '#cbd5e1'
        LINE_COLOR = '#2563eb'     # 蓝线
        FILL_TOP = 'rgba(37,99,235,0.15)'
        FILL_BOTTOM = 'rgba(37,99,235,0.01)'

    # ---- 转换数据为 Highcharts 格式 ----
    points = []
    for idx, val in equity_series.items():
        ts = int(idx.timestamp() * 1000)
        points.append([ts, round(float(val), 2)])

    # ---- 标题：左标题 + 右金额（用 subtitle 分离，避免重叠）----
    profit_pct = round((final_value - ref_value) / ref_value * 100, 2)
    sign = '+' if profit_pct >= 0 else ''
    pct_color = LINE_COLOR if profit_pct >= 0 else '#ef4444'
    title_text = '净值曲线'
    subtitle_text = f'<span style="font-size:14px;color:{pct_color}">Y{final_value:,.0f} &nbsp; {sign}{profit_pct}%</span>'

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.bootcdn.net/ajax/libs/highcharts/11.4.0/highstock.js"></script>
<style>
*{{margin:0;padding:0}}
html,body{{width:100%;height:100%;background:transparent}}
#ec{{width:100%;height:100%}}
.hc-title{{display:flex;justify-content:space-between;align-items:center}}
</style></head>
<body><div id="ec"></div>
<script>
(function(){{
var points={_json.dumps(points)};
var refVal={ref_value};

Highcharts.setOptions({{
  lang:{{
    months:['一月','二月','三月','四月','五月','六月','七月','八月','九月','十月','十一月','十二月'],
    shortMonths:['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'],
    weekdays:['星期日','星期一','星期二','星期三','星期四','星期五','星期六']
  }}
}});

Highcharts.stockChart('ec',{{
  chart:{{
    backgroundColor:'transparent',spacing:[15,15,8,8],
    panning:{{enabled:true,type:'x'}},
    zooming:{{type:'x',mouseWheel:{{enabled:true}}}},
    marginRight:15,marginTop:45
  }},
  title:{{
    text:'{title_text}',align:'left',x:0,
    style:{{color:'{TEXT}',fontSize:'15px',fontWeight:'bold'}},
    floating:true,y:12
  }},
  subtitle:{{
    text:'{subtitle_text}',align:'right',x:0,useHTML:true,
    style:{{color:'{TEXT}',fontSize:'14px'}},
    floating:true,y:12
  }},
  rangeSelector:{{enabled:false}},
  navigator:{{
    enabled:true,height:36,maskFill:'rgba(128,128,128,0.15)',
    margin:30,
    series:{{type:'area',color:'{LINE_COLOR}',fillColor:'{FILL_TOP}',lineWidth:1}},
    xAxis:{{labels:{{style:{{color:'{TEXT}',fontSize:'10px'}}}},gridLineColor:'{GRID}'}},
    handles:{{backgroundColor:'#666',borderColor:'#999'}}
  }},
  scrollbar:{{enabled:false}},
  credits:{{enabled:false}},
  tooltip:{{
    split:false,shared:true,
    backgroundColor:'{BG}',borderColor:'{CROSSHAIR}',
    style:{{color:'{TEXT}',fontSize:'12px'}},
    xDateFormat:'%Y年%m月%d日',
    headerFormat:'<b>{{point.key}}</b><br/>',
    pointFormat:'净值: <b>¥{{point.y:,.2f}}</b>'
  }},
  crosshair:{{
    color:'{CROSSHAIR}',dashStyle:'dash',
    label:{{enabled:true,style:{{color:'{TEXT}'}}}}
  }},
  plotOptions:{{
    series:{{states:{{inactive:{{opacity:1}}}}}},
    area:{{marker:{{enabled:false,states:{{hover:{{enabled:true,radius:4}}}}}}}}
  }},
  legend:{{enabled:false}},
  yAxis:[{{
    labels:{{align:'left',x:0,style:{{color:'{TEXT}',fontSize:'12px'}},format:'{{value:,.0f}}'}},
    gridLineColor:'{GRID}',gridLineWidth:0.5,
    opposite:false,lineColor:'{GRID}',tickColor:'{TEXT}',
    showFirstLabel:true,showLastLabel:true,
    minPadding:0.08,maxPadding:0.08,
    plotLines:[{{
      value:refVal,color:'{CROSSHAIR}',dashStyle:'dash',width:1,zIndex:1,
      label:{{text:'初始 Y{ref_value:,.0f}',align:'right',verticalAlign:'top',x:-8,y:-4,style:{{color:'{TEXT}',fontSize:'10px'}}}}
    }}]
  }}],
  xAxis:{{
    labels:{{style:{{color:'{TEXT}',fontSize:'11px'}}}},
    gridLineColor:'{GRID}',lineColor:'{GRID}',tickColor:'{GRID}'
  }},
  series:[{{
    type:'area',name:'净值',data:points,
    color:'{LINE_COLOR}',lineWidth:2,
    fillColor:{{
      linearGradient:{{x1:0,y1:0,x2:0,y2:1}},
      stops:[[0,'{FILL_TOP}'],[1,'{FILL_BOTTOM}']]
    }},
    threshold:refVal,
    negativeColor:'#ef4444',
    negativeFillColor:{{
      linearGradient:{{x1:0,y1:0,x2:0,y2:1}},
      stops:[[0,'rgba(239,68,68,0.20)'],[1,'rgba(239,68,68,0.01)']]
    }},
    tooltip:{{valueDecimals:2,valuePrefix:'¥'}}
  }}]
}});
}})();
</script></body></html>'''

    return html


# ============================================================
# 图表二：最大回撤曲线（Plotly）
# ============================================================

def plot_drawdown(equity_series):
    """
    绘制最大回撤曲线 —— 填充面积图展示回撤深度

    Args:
        equity_series: pd.Series，索引为日期，值为每日权益

    Returns:
        plotly.graph_objects.Figure
    """
    cum_max = equity_series.expanding().max()
    drawdown = (equity_series - cum_max) / cum_max * 100  # 回撤百分比

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=drawdown.index, y=drawdown,
        mode='lines', name='回撤 (%)',
        fill='tozeroy',                    # 填充到零线，更直观
        line=dict(color='red')
    ))
    fig.update_layout(
        title='最大回撤曲线',
        height=300
    )
    fig.update_yaxes(title_text="回撤 (%)")
    return fig


# ============================================================
# 图表三：K 线图 + 买卖标记（Highcharts Stock 交互式）
# ============================================================

def plot_kline_with_signals(data, trades_df):
    """
    使用 Highcharts Stock 渲染交互式 K 线图
    特性：Navigator 全景图、十字光标、时间范围选择器、买卖点标记、成交量柱

    Args:
        data:      包含 OHLCV 和信号列的 DataFrame
        trades_df: 交易明细 DataFrame（含 BUY/SELL 记录）
    """
    # ---- 检测 Streamlit 主题（明/暗模式自适应）----
    try:
        # 直接读取实际背景色判断，比 theme.base 更可靠（避免"跟随系统"时返回 None）
        bg_check = st.get_option('theme.backgroundColor')
        is_dark = (bg_check or '') in ('#0e1117', '#0d1117', '#0a0a0a', '#000000')
    except Exception:
        is_dark = True  # 无法检测时默认暗黑

    # 配色方案 — 文字使用中灰色 #94a3b8，黑白底色均可读
    RED = '#cf2a2a'
    GREEN = '#009975'
    TEXT = '#94a3b8'  # Tailwind slate-400，偏亮灰
    if is_dark:
        BG = '#0d1117'
        GRID = '#1a2535'
        CROSSHAIR = '#30363d'
        NAV_COLOR = '#444'
        NAV_FILL = 'rgba(255,255,255,0.05)'
    else:
        BG = '#ffffff'
        GRID = '#e8e8e8'
        CROSSHAIR = '#d0d0d0'
        NAV_COLOR = '#999'
        NAV_FILL = 'rgba(0,0,0,0.03)'

    # ---- 转换 OHLC 数据为 Highcharts 格式 ----
    ohlc = []
    volumes = []
    for idx, row in data.iterrows():
        ts = int(idx.timestamp() * 1000)  # JavaScript 毫秒时间戳
        o = round(float(row['open']), 2)
        h = round(float(row['high']), 2)
        l = round(float(row['low']), 2)
        c = round(float(row['close']), 2)
        v = int(row['volume'])
        is_up = c >= o  # 阳线/阴线判断
        ohlc.append([ts, o, h, l, c])
        volumes.append({
            'x': ts, 'y': v,
            'color': RED if is_up else GREEN,  # 红涨绿跌
            'up': is_up
        })

    # ---- 买卖标记数据（方框标记，置于 K 线外部）----
    buy_flags = []
    sell_flags = []
    if trades_df is not None and not trades_df.empty:
        for _, row in trades_df.iterrows():
            ts = int(row['date'].timestamp() * 1000)
            trade_date = row['date']
            # 查找该交易日对应的 OHLC，用于确定标记摆放高度
            if trade_date in data.index:
                h_val = round(float(data.loc[trade_date, 'high']), 2)
                l_val = round(float(data.loc[trade_date, 'low']), 2)
            else:
                h_val = round(float(row.get('price', 0)), 2)
                l_val = h_val

            if row['action'] == 'BUY':
                reason = row.get('entry_reason', '')
                buy_flags.append({
                    'x': ts,
                    'y': h_val,           # 方框置于最高价上方
                    'title': 'B',
                    'text': f"买入 {row['price']:.2f}" + (f"<br/>({reason})" if reason else "")
                })
            else:
                profit = row.get('profit_pct', None)
                reason = row.get('reason', '')
                txt = f"卖出 {row['price']:.2f}"
                if profit is not None:
                    txt += f" | {profit:+.2f}%"
                if reason:
                    txt += f"<br/>({reason})"
                sell_flags.append({
                    'x': ts,
                    'y': l_val,           # 方框置于最低价下方
                    'title': 'S',
                    'text': txt
                })

    # ---- 构建 Highcharts Stock HTML ----
    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.bootcdn.net/ajax/libs/highcharts/11.4.0/highstock.js">
</script>
<style>
*{{margin:0;padding:0}}
html,body{{width:100%;height:100%;background:transparent}}
#hc{{width:100%;height:100%}}
</style></head>
<body><div id="hc"></div>
<script>
(function(){{
var ohlc={json.dumps(ohlc)};
var volumes={json.dumps(volumes)};
var buyFlags={json.dumps(buy_flags)};
var sellFlags={json.dumps(sell_flags)};
var RED="{RED}",GREEN="{GREEN}",TEXT="{TEXT}",GRID="{GRID}",
    CROSS="{CROSSHAIR}",BG="{BG}",NAVC="{NAV_COLOR}",NAVF="{NAV_FILL}";

Highcharts.setOptions({{
  lang:{{
    months:['一月','二月','三月','四月','五月','六月','七月','八月','九月','十月','十一月','十二月'],
    shortMonths:['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'],
    weekdays:['星期日','星期一','星期二','星期三','星期四','星期五','星期六']
  }}
}});

var chart=Highcharts.stockChart('hc',{{
  chart:{{
    backgroundColor:'transparent',spacing:[5,5,10,5],
    zooming:{{mouseWheel:{{enabled:true}}}},              // 仅滚轮=缩放
    panning:{{enabled:true,type:'x'}},                    // 拖动=平移时间窗口
    resetZoomButton:{{theme:{{display:'none'}}}},
    marginRight:10
  }},
  title:{{text:'K线图与买卖点',align:'left',x:0,
    style:{{color:TEXT,fontSize:'16px',fontWeight:'bold'}}}},

  // ======= 范围选择器（右上角浮动，与标题同行）=======
  rangeSelector:{{
    buttons:[
      {{type:'month',count:1,text:'1月'}},
      {{type:'month',count:3,text:'3月'}},
      {{type:'month',count:6,text:'半年'}},
      {{type:'year', count:1,text:'1年'}},
      {{type:'all',text:'全部'}}
    ],
    selected:4,inputEnabled:false,
    buttonTheme:{{style:{{color:TEXT}}}},
    floating:true,
    buttonPosition:{{align:'right',x:0,y:-35}},
    verticalAlign:'top'
  }},

  // ======= Navigator 迷你全景图（雪球同款）=======
  navigator:{{
    enabled:true,height:42,maskFill:'rgba(128,128,128,0.2)',
    series:{{type:'area',color:NAVC,fillColor:NAVF,lineWidth:1}},
    xAxis:{{labels:{{style:{{color:TEXT}}}},gridLineColor:GRID}},
    handles:{{backgroundColor:'#666',borderColor:'#999'}}
  }},
  scrollbar:{{enabled:false}},

  // ======= 十字光标（中文金融术语）=======
  tooltip:{{split:true,shared:true,
    backgroundColor:BG,borderColor:CROSS,
    style:{{color:TEXT,fontSize:'12px'}},
    dateTimeLabelFormats:{{day:'%Y年%m月%d日'}}
  }},
  crosshair:{{color:CROSS,dashStyle:'dot'}},

  // ======= 禁止悬停时其他系列变暗 =======
  plotOptions:{{
    series:{{states:{{inactive:{{opacity:1}}}}}},
    candlestick:{{states:{{hover:{{brightness:0}}}}}},
    column:{{states:{{hover:{{brightness:0}}}}}}
  }},

  // ======= 图例 =======
  legend:{{
    align:'left',verticalAlign:'bottom',y:-5,
    itemStyle:{{color:TEXT}},itemHoverStyle:{{color:TEXT}},
    backgroundColor:'transparent'
  }},

  // ======= Y 轴：价格左侧 / 成交量右侧（错开布局，防止重叠）=======
  yAxis:[{{
    labels:{{enabled:true,align:'left',x:0,
      style:{{color:TEXT,fontSize:'14px'}}}},
    gridLineColor:GRID,gridLineWidth:0.5,
    opposite:false,lineColor:GRID,tickColor:TEXT,
    tickLength:5,tickWidth:1,tickAmount:7,
    showFirstLabel:true,showLastLabel:true,
    height:'66%',
    resize:{{enabled:true}}
  }},{{
    labels:{{enabled:false}},gridLineWidth:0,
    opposite:true,top:'70%',height:'30%',
    lineWidth:0,tickWidth:0,offset:0
  }}],

  // ======= X 轴 =======
  xAxis:{{
    labels:{{style:{{color:TEXT,fontSize:'14px'}}}},
    gridLineColor:GRID,lineColor:GRID,tickColor:GRID
  }},

  // ======= 数据系列 =======
  series:[{{
    // K 线主图
    id:'kline',type:'candlestick',name:'K线',data:ohlc,
    upColor:RED,color:GREEN,upLineColor:RED,lineColor:GREEN,
    tooltip:{{pointFormat:'开盘: <b>{{point.open:.2f}}</b><br/>最高: <b>{{point.high:.2f}}</b><br/>最低: <b>{{point.low:.2f}}</b><br/>收盘: <b>{{point.close:.2f}}</b>'}},
    dataGrouping:{{enabled:true,forced:true,units:[
      ['day',[1]],['week',[1]],['month',[1]],['year',[1]]
    ]}}
  }},{{
    // 成交量副图
    type:'column',name:'成交量',data:volumes,yAxis:1,
    turboThreshold:0,dataGrouping:{{enabled:true,forced:true}},
    tooltip:{{pointFormat:'成交量: <b>{{point.y:,.0f}}</b> 手'}}
  }},{{
    // 买入标记 — 红色方框，置于 K 线最高价上方
    type:'flags',name:'买入',data:buyFlags,yAxis:0,
    color:RED,fillColor:RED,shape:'squarepin',
    style:{{color:'#ffffff',fontSize:'11px',fontWeight:'bold'}},
    tooltip:{{pointFormat:'{{point.text}}'}},
    y:-30,clip:false,allowOverlapX:true,
    width:8,zIndex:5
  }},{{
    // 卖出标记 — 绿色方框，置于 K 线最低价下方
    type:'flags',name:'卖出',data:sellFlags,yAxis:0,
    color:GREEN,fillColor:GREEN,shape:'squarepin',
    style:{{color:'#ffffff',fontSize:'11px',fontWeight:'bold'}},
    tooltip:{{pointFormat:'{{point.text}}'}},
    y:30,clip:false,allowOverlapX:true,
    width:8,zIndex:5
  }}]
}});
}})();
</script></body></html>'''

    # 嵌入 Streamlit 页面
    st.components.v1.html(html, height=600, scrolling=False)
