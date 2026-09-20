"""Conservative candidate motor-road filter; does not assert operational legality."""
import json

MOTOR_HIGHWAYS={'motorway','motorway_link','trunk','trunk_link','primary','primary_link',
                'secondary','secondary_link','tertiary','tertiary_link','unclassified',
                'residential','living_street','service'}


def motor_edges(edges):
    def allowed(row):
        if row.highway not in MOTOR_HIGHWAYS:return False
        tags=json.loads(row.osm_tags_json or '{}')
        if any(k.endswith(':conditional') for k in tags if k in {'access:conditional','vehicle:conditional','motor_vehicle:conditional','motorcar:conditional'}):
            return False
        # Specific vehicle restrictions override general access.
        value=next((str(tags[k]).lower() for k in ['motorcar','motor_vehicle','vehicle','access'] if k in tags),'yes')
        return value not in {'no','private','agricultural','forestry','customers','delivery','destination','permit'}
    return edges.loc[[allowed(row) for row in edges.itertuples()]].copy()
