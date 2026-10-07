"""Adapt the supplied edge-damage group for dense open-backed relief.
Retain its noise/remap/normal-offset machinery; omit volume/boolean/remesh.
"""
import bpy

def set_input(modifier,identifier,value):
    if hasattr(modifier,'properties'):getattr(modifier.properties.inputs,identifier).value=value
    else:modifier[identifier]=value

def make_group(library):
    with bpy.data.libraries.load(str(library),link=False) as (src,dst):
        if 'Mesh Edge Damage' not in src.node_groups:raise ValueError('Mesh Edge Damage not found.')
        dst.node_groups=['Mesh Edge Damage']
    group=dst.node_groups[0].copy();group.name='Contour Relief - Local Edge Wear'
    nodes,links=group.nodes,group.links
    source=next(n for n in nodes if n.bl_idname=='NodeGroupInput')
    # Feed dense geometry directly, avoiding a voxel stair-step after smoothing.
    target=nodes['Set Position']
    for l in list(target.inputs['Geometry'].links):links.remove(l)
    links.new(source.outputs['Geometry'],target.inputs['Geometry'])
    attr=nodes.new('GeometryNodeInputNamedAttribute');attr.data_type='FLOAT';attr.inputs['Name'].default_value='alpha_edge_weight';attr.label='Sparse peripheral wear zones'
    mul=nodes.new('ShaderNodeMath');mul.operation='MULTIPLY'
    links.new(nodes['Math.002'].outputs[0],mul.inputs[0]);links.new(attr.outputs['Attribute'],mul.inputs[1])
    scale=nodes['Vector Math.002']
    for l in list(scale.inputs['Scale'].links):links.remove(l)
    links.new(mul.outputs[0],scale.inputs['Scale'])
    # Broad shallow dents are a separate, explicitly positioned shape field.
    dent=nodes.new('GeometryNodeInputNamedAttribute');dent.data_type='FLOAT';dent.inputs['Name'].default_value='wear_z';dent.label='Two broad shallow depressions'
    vec=nodes.new('ShaderNodeCombineXYZ');links.new(dent.outputs['Attribute'],vec.inputs['Z'])
    second=nodes.new('GeometryNodeSetPosition');second.label='Local broad depressions'
    links.new(target.outputs['Geometry'],second.inputs['Geometry']);links.new(vec.outputs[0],second.inputs['Offset'])
    out=nodes['Group Output']
    for l in list(out.inputs[0].links):links.remove(l)
    links.new(second.outputs[0],out.inputs[0])
    # Keep only nodes contributing to output; the source group remains intact.
    keep=set();stack=[out]
    while stack:
        n=stack.pop()
        if n in keep:continue
        keep.add(n)
        stack.extend(l.from_node for s in n.inputs for l in s.links)
    for n in list(nodes):
        if n not in keep:nodes.remove(n)
    for s in group.interface.items_tree:
        if s.item_type=='SOCKET' and s.in_out=='INPUT':
            defaults={'Smooth Mesh Iterations':0,'Noise Strength':.0009,'Level Offset':0.0,'Scale':65.0,'Detail':1.0,'Roughness':.35,'From Min':.30,'From Max':.72}
            if s.name in defaults:s.default_value=defaults[s.name]
    attr.location=(-180,-540);mul.location=(40,-420);scale.location=(260,-300);target.location=(470,0);dent.location=(470,-320);vec.location=(690,-240);second.location=(920,0);out.location=(1170,0)
    group['source_library']=str(library);group['notes']='Original noise/remap retained. Dense contour geometry directly displaced; no remesh, no blur, no boolean, no back cap. Attribute restricts wear to peripheral zones.'
    return group

def attach(obj,group):
    mod=obj.modifiers.new('Local Edge Damage - Contour Preserving','NODES');mod.node_group=group
    for s in group.interface.items_tree:
        if s.item_type=='SOCKET' and s.in_out=='INPUT':
            defaults={'Smooth Mesh Iterations':0,'Noise Strength':.0009,'Level Offset':0.0,'Scale':65.0,'Detail':1.0,'Roughness':.35,'From Min':.30,'From Max':.72}
            if s.name in defaults:set_input(mod,s.identifier,defaults[s.name])
    return mod
