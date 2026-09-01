from app.models import Agent, Component, Decision, Event, Memory, Project, Relationship, Role, Task, User

def seed_demo(repo):
    if repo.list_projects(): return
    project=repo.create_project(Project(name="NodeFlow AI SaaS", description="Shared intelligence for AI-enabled teams.", repository_url="https://github.com/PREMBISOY/nodeflow.git"))
    owner=repo.create_user(User(project_id=project.id,name="Aayush",role="Product Owner",permissions=["admin","project:read"]))
    repo.create_role(Role(project_id=project.id,name="Product Owner",permissions=["project:read"],description="Owns product-level project knowledge."))
    components={name: repo.create_component(Component(project_id=project.id,name=name,type=kind,description=description)) for name,kind,description in [("Frontend","application","Collaborative React workspace"),("Backend API","api","FastAPI project-intelligence API"),("ML Service","service","Recommendation and analysis service"),("Database","database","PostgreSQL/Supabase knowledge store"),("Authentication","service","Identity and access control")]} 
    for source,target in [("Frontend","Backend API"),("Backend API","ML Service"),("Backend API","Database"),("Backend API","Authentication")]: repo.create_relationship(Relationship(project_id=project.id,source_entity_id=components[source].id,target_entity_id=components[target].id,relationship_type="DEPENDS_ON"))
    agents={role:repo.create_agent(Agent(project_id=project.id,owner_id=owner.id,name=role,provider="NodeFlow",model="demo",role=role,capabilities=["project_context"])) for role in ["Backend Agent","Frontend Agent","ML Agent","Product Agent","Marketing Agent"]}
    repo.create_task(Task(project_id=project.id,title="Persist project event stream",description="Write durable collaboration history",agent_id=agents["Backend Agent"].id,status="IN_PROGRESS",priority="HIGH",affected_components=[components["Backend API"].id,components["Database"].id]))
    repo.create_task(Task(project_id=project.id,title="Integrate recommendations UI",agent_id=agents["Frontend Agent"].id,status="TODO",affected_components=[components["Frontend"].id,components["Backend API"].id]))
    repo.create_decision(Decision(project_id=project.id,title="Use PostgreSQL",decision="Use PostgreSQL/Supabase for project knowledge.",rationale="Relational consistency is required for project state.",created_by=owner.id,affected_components=[components["Database"].id]))
    repo.create_memory(Memory(project_id=project.id,type="PROJECT_FACT",content="Frontend depends on Backend API, which coordinates ML Service and Database.",source="golden-demo",related_components=[components["Frontend"].id,components["Backend API"].id]))
    repo.create_event(Event(project_id=project.id,event_type="PROJECT_INITIALIZED",description="Golden demo project initialized",affected_components=list(c.id for c in components.values())))
