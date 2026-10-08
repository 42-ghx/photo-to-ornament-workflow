"""Generate the offline viewer, JSON Canvas interchange file and README preview."""
import json
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / 'canvas'


def text_for(node):
    text = f"## {node['title']}\n\n{node['summary']}\n\n**状态：{node['status']}**\n\n输入：{node['input']}\n\n输出：{node['output']}"
    if node.get('rules'):
        text += '\n\n' + '\n'.join('- ' + rule for rule in node['rules'])
    if node.get('params'):
        text += '\n\n' + '\n\n'.join(f'{key}：{value}' for key, value in node['params'])
    if node.get('command'):
        text += '\n\n```sh\n' + node['command'] + '\n```'
    if node.get('assets'):
        text += '\n\n### 关联文件\n\n' + '\n'.join(
            f'- [{label}](../{path})' for label, path in node['assets'])
    if node.get('note'):
        text += '\n\n<!-- ornament-note -->\n' + node['note']
    return text


def main():
    source = json.loads((CANVAS / 'workflow.json').read_text(encoding='utf-8'))
    all_ids = [node['id'] for node in source['nodes']] + [group['id'] for group in source['groups']]
    assert len(set(all_ids)) == len(all_ids)
    ids = {node['id'] for node in source['nodes']}
    for edge in source['edges']:
        assert edge['fromNode'] in ids and edge['toNode'] in ids
    template = (CANVAS / 'template.html').read_text(encoding='utf-8')
    assert template.count('__WORKFLOW_DATA__') == 1
    payload = json.dumps(source, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (CANVAS / 'index.html').write_text(template.replace('__WORKFLOW_DATA__', payload), encoding='utf-8', newline='\n')
    groups = [{key: group[key] for key in ('id', 'x', 'y', 'width', 'height')} | {'type': 'group', 'label': group['label']} for group in source['groups']]
    nodes = [{key: node[key] for key in ('id', 'x', 'y', 'width', 'height')} | {
        'type': 'text', 'text': text_for(node), 'color': '2' if node['category'] == 'optional' else '6' if node['category'] == 'future' else '5' if node['category'] in ('image', 'map') else '4'
    } for node in source['nodes']]
    edges = [{key: edge[key] for key in ('id', 'fromNode', 'fromSide', 'toNode', 'toSide')} | {'toEnd': 'arrow'} | ({'label': edge['label']} if edge.get('label') else {}) for edge in source['edges']]
    (CANVAS / 'photo-to-ornament.canvas').write_text(json.dumps({'nodes': groups + nodes, 'edges': edges}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

    overview(source)
    print(json.dumps({'status': 'generated', 'workflow_nodes': len(nodes), 'groups': len(groups), 'edges': len(edges)}))


def overview(source):
    # Compact preview for GitHub. Detailed, editable nodes stay in the canvas.
    titles = [
        ('原照片 / 任务定义', '区域、尺寸与观看距离', 'image'),
        ('透明抠图', '去除背景、展台和投影', 'image'),
        ('柔和去光照', '减弱反光，保留读形', 'image'),
        ('材料遮罩', '白色材料 / 黑色贯通孔', 'image'),
        ('连续高度图', '坡度、眼睛与刻线', 'image'),
        ('地图检查', '完整、对齐、语义一致', 'check'),
        ('高模 · 环带 · UV', '轮廓内高密度四边面', 'mesh'),
        ('浮雕强度 × 0.5', '原细节保留，底厚不变', 'mesh'),
        ('几何与 UV 检查', '孔洞、厚度、法线与接缝', 'check'),
        ('FBX · 工程 · 回读', '坐标 / 面数 / UV 验证', 'mesh'),
        ('Blender 查看', '核实本机连接或云端文件', 'mesh'),
        ('可选磨损 · 复验', '局部权重；当前模型未应用', 'optional'),
    ]
    colors = {'image': '#92b8d0', 'mesh': '#98c8b5', 'check': '#98c8b5', 'optional': '#d4b18c'}
    positions = [(44 + (i % 3) * 294, 124 + (i // 3) * 185) for i in range(12)]
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="916" height="880" viewBox="0 0 916 880" role="img" aria-labelledby="title desc">',
             '<title id="title">照片转镂空纹样高模：节点流程预览</title>',
             '<desc id="desc">图像生成阶段分开材料遮罩与连续高度；高模含厚度循环边与分区UV；只将浮雕起伏减半；FBX重导入后查看。磨损为可选且尚未应用。</desc>',
             '<rect width="916" height="880" fill="#14181c" rx="16"/>',
             '<g font-family="Microsoft YaHei,system-ui,sans-serif">',
             '<text x="44" y="48" fill="#e8eceb" font-size="25" font-weight="500">照片 → 镂空纹样高模</text>',
             '<text x="44" y="78" fill="#a9b3b8" font-size="14">保留 Before 原细节 · 刻线写进高度 · 孔洞写进遮罩</text>',
             '<defs><marker id="a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8Z" fill="#84979b"/></marker></defs>']
    def connect(a, b, vertical=False, optional=False):
        ax, ay = positions[a]; bx, by = positions[b]
        if vertical:
            x1, y1, x2, y2 = ax + 120, ay + 124, bx + 120, by
            middle = (y1 + y2) / 2
            d = f'M{x1} {y1} C{x1} {middle} {x2} {middle} {x2} {y2}'
        else:
            x1, y1, x2, y2 = ax + 240, ay + 62, bx, by + 62
            middle = (x1 + x2) / 2
            d = f'M{x1} {y1} C{middle} {y1} {middle} {y2} {x2} {y2}'
        dash = ' stroke-dasharray="5 5"' if optional else ''
        parts.append(f'<path d="{d}" fill="none" stroke="#657a7f" stroke-width="2" marker-end="url(#a)"{dash}/>')
    for a, b in [(0,1),(1,2),(3,4),(4,5),(6,7),(7,8),(9,10)]:
        connect(a,b)
    connect(2,3,True); connect(2,4,True)
    connect(5,6,True); connect(8,9,True); connect(10,11,False,True)
    for i, ((title, summary, category), (x,y)) in enumerate(zip(titles,positions)):
        color = colors[category]
        label = '可选 / 未应用' if category == 'optional' else '输入' if i == 0 else '已验证'
        parts.extend([f'<rect x="{x}" y="{y}" width="240" height="124" rx="9" fill="#232c33" stroke="#364149"/>',
                      f'<text x="{x+15}" y="{y+26}" fill="{color}" font-size="12">{i+1:02d} · {label}</text>',
                      f'<text x="{x+15}" y="{y+60}" fill="#e8eceb" font-size="18" font-weight="500">{escape(title)}</text>',
                      f'<text x="{x+15}" y="{y+89}" fill="#a9b3b8" font-size="13">{escape(summary)}</text>'])
    parts.extend(['<text x="44" y="850" fill="#a9b3b8" font-size="13">可拖动、缩放、查看约束与命令；节点画布不自动执行建模。</text>','</g></svg>'])
    (CANVAS / 'overview.svg').write_text('\n'.join(parts)+'\n',encoding='utf-8',newline='\n')


if __name__ == '__main__':
    main()
