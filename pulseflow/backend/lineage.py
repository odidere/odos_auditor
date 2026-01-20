import networkx as nx


class ImpactAnalyzer:
    def __init__(self, edges):
        """
        Initializes with a list of dependencies.
        Edges format: [('upstream_task', 'downstream_task'), ...]
        """
        self.graph = nx.DiGraph()
        if edges:
            self.graph.add_edges_from(edges)

    def calculate_blast_radius(self, offending_task_id: str):
        """
        Identifies every downstream asset affected by an upstream offender.
        """
        if offending_task_id not in self.graph:
            return []

        # Find all nodes reachable from the offending task
        affected_nodes = list(nx.descendants(self.graph, offending_task_id))

        # Categorize the impact (Enterprise Classification)
        impact_report = []
        for node in affected_nodes:
            category = "DASHBOARD" if "db_" in node.lower(
            ) or "view" in node.lower() else "TABLE"
            if "ml_" in node.lower():
                category = "ML_MODEL"

            impact_report.append({
                "asset_id": node,
                "type": category,
                "criticality": "HIGH" if category in ["DASHBOARD", "ML_MODEL"] else "MEDIUM"
            })

        return impact_report

    def get_critical_path_delay(self, task_id, duration_increase):
        """
        Estimates the delay for the final delivery asset.
        """
        # Simplistic implementation: assumes duration_increase pushes the whole path back
        return {
            "target_task": task_id,
            "estimated_delay_sec": duration_increase,
            "sla_violation_risk": "HIGH" if duration_increase > 300 else "LOW"
        }
