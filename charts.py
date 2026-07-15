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
# 图表一：净值曲线（Plotly）
# ============================================================

def plot_equity(equity_series):
    """
    绘制回测净值曲线 —— 使用 Plotly 平滑折线图

    Args:
        equity_series: pd.Series，索引为日期，值为每日权益

    Returns:
        plotly.graph_objects.Figure
    """
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity_series.index,
        y=equity_series,
        mode='lines',
        name='净值',
        line=dict(color='#1f77b4', width=2.5),  # 蓝线
        line_shape='spline'                       # 平滑曲线
    ))
    fig.update_layout(
        title='净值曲线',
        height=400,
        margin=dict(l=40, r=40, t=40, b=40)
    )
    fig.update_yaxes(title_text="净值")
    return fig


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

    # ---- 买卖标记数据（flags 系列）----
    buys = []
    sells = []
    if trades_df is not None and not trades_df.empty:
        for _, row in trades_df.iterrows():
            ts = int(row['date'].timestamp() * 1000)
            if row['action'] == 'BUY':
                reason = row.get('entry_reason', '')
                buys.append({
                    'x': ts, 'title': '多',
                    'text': f"买入 {row['price']:.2f}" + (f" ({reason})" if reason else "")
                })
            else:
                profit = row.get('profit_pct', None)
                reason = row.get('reason', '')
                txt = f"卖出 {row['price']:.2f}"
                if profit is not None:
                    txt += f" | {profit:+.2f}%"
                if reason:
                    txt += f" | {reason}"
                sells.append({'x': ts, 'title': '空', 'text': txt})

    # ---- 构建 Highcharts Stock HTML ----
    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.bootcdn.net/ajax/libs/highcharts/11.4.0/highstock.js">
</script>
<style>
*{{margin:0;padding:0}}
html,body{{width:100%;height:100%;background:transparent;overflow:hidden}}
#hc{{width:100%;height:100%}}
</style></head>
<body><div id="hc"></div>
<script>
(function(){{
var ohlc={json.dumps(ohlc)};
var volumes={json.dumps(volumes)};
var buys={json.dumps(buys)};
var sells={json.dumps(sells)};
var RED="{RED}",GREEN="{GREEN}",TEXT="{TEXT}",GRID="{GRID}",
    CROSS="{CROSSHAIR}",BG="{BG}",NAVC="{NAV_COLOR}",NAVF="{NAV_FILL}";

Highcharts.stockChart('hc',{{
  chart:{{
    backgroundColor:'transparent',spacing:[5,5,10,5],
    panning:true,zoomType:'x',marginRight:10
  }},
  title:{{text:'K线图与买卖点',align:'left',x:0,
    style:{{color:TEXT,fontSize:'16px',fontWeight:'bold'}}}},

  // ======= 范围选择器（快速切换时间范围）=======
  rangeSelector:{{
    buttons:[
      {{type:'month',count:1,text:'1月'}},
      {{type:'month',count:3,text:'3月'}},
      {{type:'month',count:6,text:'半年'}},
      {{type:'year', count:1,text:'1年'}},
      {{type:'all',text:'全部'}}
    ],
    selected:4,inputEnabled:false,
    buttonTheme:{{style:{{color:TEXT}}}}
  }},

  // ======= Navigator 迷你全景图（雪球同款）=======
  navigator:{{
    enabled:true,height:42,maskFill:'rgba(128,128,128,0.2)',
    series:{{type:'area',color:NAVC,fillColor:NAVF,lineWidth:1}},
    xAxis:{{labels:{{style:{{color:TEXT}}}},gridLineColor:GRID}},
    handles:{{backgroundColor:'#666',borderColor:'#999'}}
  }},
  scrollbar:{{enabled:false}},

  // ======= 十字光标 =======
  tooltip:{{split:true,shared:true,
    backgroundColor:BG,borderColor:CROSS,
    style:{{color:TEXT,fontSize:'12px'}}
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
    tooltip:{{valueDecimals:2}},
    dataGrouping:{{enabled:true,forced:true,units:[
      ['day',[1]],['week',[1]],['month',[1]],['year',[1]]
    ]}}
  }},{{
    // 成交量副图
    type:'column',name:'成交量',data:volumes,yAxis:1,
    turboThreshold:0,dataGrouping:{{enabled:true,forced:true}},
    tooltip:{{pointFormat:'成交量: <b>{{point.y:,.0f}}</b> 手'}}
  }},{{
    // 买入标记
    type:'flags',name:'买入',data:buys,onSeries:'kline',
    color:RED,fillColor:'rgba(0,0,0,0)',shape:'squarepin',
    style:{{color:RED,fontSize:'10px',fontWeight:'bold'}},
    tooltip:{{pointFormat:'{{point.text}}'}}
  }},{{
    // 卖出标记
    type:'flags',name:'卖出',data:sells,onSeries:'kline',
    color:GREEN,fillColor:'rgba(0,0,0,0)',shape:'squarepin',
    style:{{color:GREEN,fontSize:'10px',fontWeight:'bold'}},
    tooltip:{{pointFormat:'{{point.text}}'}}
  }}]
}});
}})();
</script></body></html>'''

    # 嵌入 Streamlit 页面
    st.components.v1.html(html, height=600, scrolling=False)
