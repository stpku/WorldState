"""Independently inspect IFC identities and unaffected object geometry."""
import argparse
import hashlib
import json
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate

from products.worldstate_bim.room_ifc import stable_guid
from products.worldstate_bim.room_ir import geometry_issues, validate_room


def signature(settings, entity):
    shape=ifcopenshell.geom.create_shape(settings,entity)
    mesh=shape.geometry  # Keep the owner alive while accessing its C++ geometry buffers.
    vertices=list(mesh.verts)
    points=sorted(tuple(round(float(vertices[i+j]),6) for j in range(3)) for i in range(0,len(vertices),3))
    return hashlib.sha256(json.dumps(points,separators=(',',':')).encode()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('before-model','before-ifc','after-model','after-ifc','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--source-kind',choices=('synthetic','scan','other'),default='other')
    a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output')
    before=json.loads(a.before_model.read_text());after=json.loads(a.after_model.read_text())
    validate_room(before);validate_room(after)
    if before['project_id']!=after['project_id']:raise ValueError('different project identities')
    first=ifcopenshell.open(str(a.before_ifc));second=ifcopenshell.open(str(a.after_ifc))
    ids=lambda f:{e.GlobalId for e in f.by_type('IfcProduct') if e.GlobalId}
    before_guids,after_guids=ids(first),ids(second)
    affected=set()
    for event in after.get('history',[]):
        if event.get('revision',0)>before['revision']:affected.update(event.get('affected_elements',[]))
    settings=ifcopenshell.geom.settings();settings.set('use-world-coords',True)
    unchanged=[];unexpected=[];failures=[];compared=[]
    prior={e['id']:e for e in before['elements']};current={e['id']:e for e in after['elements']}
    for ident in sorted(prior.keys() & current.keys()):
        item=prior[ident]
        if item['ifc_type'] not in {'IfcWall','IfcSlab','IfcDoor','IfcWindow'}:continue
        guid=stable_guid(before['project_id'],item['ifc_type'],ident)
        try:
            a_shape=signature(settings,first.by_guid(guid));b_shape=signature(settings,second.by_guid(guid))
            compared.append(ident)
            if ident not in affected:
                (unchanged if a_shape==b_shape else unexpected).append(ident)
        except (RuntimeError,ValueError,AttributeError) as exc:failures.append({'id':ident,'error':str(exc)})
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(second,logger)
    result={'before_revision':before['revision'],'after_revision':after['revision'],
        'ifc_schema':second.schema,'schema_issue_count':len(logger.statements),
        'guid_count_before':len(before_guids),'guid_count_after':len(after_guids),
        'guid_sets_equal':before_guids==after_guids,'affected_elements':sorted(affected),
        'unaffected_vertex_geometry_unchanged':unchanged,'unaffected_geometry_unexpectedly_changed':unexpected,
        'geometry_compared':compared,'geometry_failures':failures,'ir_issues':geometry_issues(after),'source_kind':a.source_kind,
        'limitations':['Vertex comparison does not establish semantic correctness or a complete solid clash check.',
                       'Source classification is caller-declared; this comparison is not independent site validation.']}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
