# Multi-Tenancy Implementation Guide

## Overview

MizzouNewsCrawler uses **source-based data ownership** for multi-tenancy, where users only access data from sources they own or have been granted explicit permission to access by an admin.

---

## Architecture Principles

### 1. Data Ownership Model

- **Default**: Users can only see data from sources they created/uploaded
- **Admin Grants**: Admins can grant access to additional sources
- **Public Sources**: Admins can mark sources as public (visible to all)
- **No Tenant Isolation**: Single database, single Kubernetes namespace (simple, cost-effective)

### 2. Security Layers

```
┌─────────────────────────────────────────────┐
│  Layer 1: Authentication (OAuth 2.0)        │
│  - Verify user identity                     │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  Layer 2: Authorization (RBAC)              │
│  - Check user role (admin/editor/viewer)    │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  Layer 3: Source Access Control             │
│  - Filter data by accessible sources        │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│  Layer 4: API Response Filtering            │
│  - Only return data user can access         │
└─────────────────────────────────────────────┘
```

---

## Database Schema

### Core Tables

```sql
-- Users table
CREATE TABLE users (
    user_id VARCHAR(255) PRIMARY KEY,  -- OAuth 'sub' claim
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(255),
    role VARCHAR(50) NOT NULL DEFAULT 'viewer',  -- admin, editor, viewer
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE
);

-- Source ownership
ALTER TABLE sources ADD COLUMN owner_id VARCHAR(255) REFERENCES users(user_id);
ALTER TABLE sources ADD COLUMN created_by VARCHAR(255) REFERENCES users(user_id);
ALTER TABLE sources ADD COLUMN is_public BOOLEAN DEFAULT FALSE;
ALTER TABLE sources ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- Source permissions (explicit grants)
CREATE TABLE source_permissions (
    permission_id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    access_level VARCHAR(50) NOT NULL DEFAULT 'read',  -- read, write, admin
    granted_by VARCHAR(255) NOT NULL REFERENCES users(user_id),
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP NULL,
    UNIQUE(source_id, user_id)
);

-- Audit log for permission changes
CREATE TABLE permission_audit_log (
    audit_id SERIAL PRIMARY KEY,
    action VARCHAR(50) NOT NULL,  -- grant, revoke, modify
    source_id INTEGER REFERENCES sources(source_id),
    user_id VARCHAR(255) REFERENCES users(user_id),
    performed_by VARCHAR(255) NOT NULL REFERENCES users(user_id),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details JSONB
);

-- Indexes for performance
CREATE INDEX idx_source_permissions_user ON source_permissions(user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_source_permissions_source ON source_permissions(source_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_sources_owner ON sources(owner_id);
CREATE INDEX idx_sources_public ON sources(is_public) WHERE is_public = TRUE;
CREATE INDEX idx_articles_source ON articles(source_id);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_permission_audit_user ON permission_audit_log(user_id);
```

---

## Backend Implementation (FastAPI)

### 1. User Authentication

```python
# backend/app/auth.py
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from jose import JWTError, jwt
from typing import Optional

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://accounts.google.com/o/oauth2/v2/auth",
    tokenUrl="https://oauth2.googleapis.com/token"
)

async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Validate JWT token and return user."""
    try:
        payload = jwt.decode(
            token,
            options={"verify_signature": False}  # Verified by OAuth provider
        )
        user_id: str = payload.get("sub")
        email: str = payload.get("email")
        
        if user_id is None or email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
        
        # Get or create user in database
        user = get_or_create_user(user_id, email, payload.get("name"))
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive"
            )
        
        # Update last login
        update_last_login(user_id)
        
        return user
    
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

def require_role(required_role: Role):
    """Decorator to require specific role."""
    async def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role != required_role and current_user.role != Role.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {required_role} role"
            )
        return current_user
    return role_checker
```

### 2. Source Access Control

```python
# backend/app/permissions.py
from sqlalchemy import select, or_, and_
from typing import List, Set

def get_accessible_source_ids(user: User, session: Session) -> Set[int]:
    """
    Get all source IDs the user can access.
    
    Access rules:
    1. Admin users can access ALL sources
    2. Regular users can access:
       - Sources they own
       - Sources with explicit permissions
       - Public sources
    """
    if user.role == Role.ADMIN:
        # Admins see everything
        result = session.execute(select(Source.source_id))
        return {row[0] for row in result}
    
    # Sources user owns
    owned_sources = select(Source.source_id).where(
        Source.owner_id == user.user_id
    )
    
    # Sources with explicit permissions (not revoked)
    permitted_sources = select(SourcePermission.source_id).where(
        and_(
            SourcePermission.user_id == user.user_id,
            SourcePermission.revoked_at.is_(None)
        )
    )
    
    # Public sources
    public_sources = select(Source.source_id).where(
        Source.is_public == True
    )
    
    # Combine all
    combined_query = owned_sources.union(permitted_sources, public_sources)
    result = session.execute(combined_query)
    
    return {row[0] for row in result}

def check_source_access(
    user: User,
    source_id: int,
    session: Session,
    required_level: str = "read"
) -> bool:
    """
    Check if user has access to a specific source.
    
    Args:
        user: Current user
        source_id: Source to check
        required_level: read, write, or admin
    
    Returns:
        True if user has required access level
    """
    if user.role == Role.ADMIN:
        return True
    
    # Check ownership
    source = session.get(Source, source_id)
    if source and source.owner_id == user.user_id:
        return True
    
    # Check if public (read-only)
    if source and source.is_public and required_level == "read":
        return True
    
    # Check explicit permissions
    permission = session.execute(
        select(SourcePermission).where(
            and_(
                SourcePermission.source_id == source_id,
                SourcePermission.user_id == user.user_id,
                SourcePermission.revoked_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    
    if not permission:
        return False
    
    # Check access level
    access_hierarchy = {"read": 1, "write": 2, "admin": 3}
    return access_hierarchy.get(permission.access_level, 0) >= access_hierarchy.get(required_level, 0)

def filter_query_by_sources(query, user: User, session: Session):
    """Apply source filtering to SQLAlchemy query."""
    accessible_sources = get_accessible_source_ids(user, session)
    return query.where(Article.source_id.in_(accessible_sources))
```

### 3. API Endpoints

```python
# backend/app/routes/articles.py
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

router = APIRouter(prefix="/articles", tags=["articles"])

@router.get("/", response_model=List[ArticleResponse])
async def get_articles(
    county: Optional[str] = None,
    source_id: Optional[int] = None,
    limit: int = Query(50, le=500),
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db)
):
    """
    Get articles filtered by user's source access.
    
    Users only see articles from sources they have access to.
    """
    # Start with base query
    query = select(Article)
    
    # Filter by county if provided
    if county:
        query = query.where(Article.county == county)
    
    # Filter by source if provided AND user has access
    if source_id:
        if not check_source_access(current_user, source_id, session):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have access to this source"
            )
        query = query.where(Article.source_id == source_id)
    
    # Apply source access filtering
    query = filter_query_by_sources(query, current_user, session)
    
    # Apply pagination
    query = query.offset(offset).limit(limit)
    
    result = session.execute(query)
    articles = result.scalars().all()
    
    return articles

@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: str,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db)
):
    """Get single article if user has access to its source."""
    article = session.get(Article, article_id)
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    if not check_source_access(current_user, article.source_id, session):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have access to this article's source"
        )
    
    return article

@router.get("/sources/accessible", response_model=List[SourceResponse])
async def get_accessible_sources(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_db)
):
    """Get all sources the user can access."""
    source_ids = get_accessible_source_ids(current_user, session)
    
    sources = session.execute(
        select(Source).where(Source.source_id.in_(source_ids))
    ).scalars().all()
    
    return sources
```

### 4. Admin Endpoints

```python
# backend/app/routes/admin.py
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/permissions/grant")
async def grant_source_permission(
    source_id: int,
    user_id: str,
    access_level: str = "read",
    current_user: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db)
):
    """
    Grant a user access to a source.
    
    Only admins can grant permissions.
    """
    # Validate source exists
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    
    # Validate user exists
    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if permission already exists
    existing = session.execute(
        select(SourcePermission).where(
            and_(
                SourcePermission.source_id == source_id,
                SourcePermission.user_id == user_id,
                SourcePermission.revoked_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    
    if existing:
        # Update existing permission
        existing.access_level = access_level
        existing.granted_by = current_user.user_id
        existing.granted_at = datetime.utcnow()
    else:
        # Create new permission
        permission = SourcePermission(
            source_id=source_id,
            user_id=user_id,
            access_level=access_level,
            granted_by=current_user.user_id
        )
        session.add(permission)
    
    # Log the action
    audit_entry = PermissionAuditLog(
        action="grant",
        source_id=source_id,
        user_id=user_id,
        performed_by=current_user.user_id,
        details={"access_level": access_level}
    )
    session.add(audit_entry)
    
    session.commit()
    
    return {"status": "success", "message": f"Granted {access_level} access to user {user_id}"}

@router.delete("/permissions/revoke")
async def revoke_source_permission(
    source_id: int,
    user_id: str,
    current_user: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db)
):
    """Revoke a user's access to a source."""
    permission = session.execute(
        select(SourcePermission).where(
            and_(
                SourcePermission.source_id == source_id,
                SourcePermission.user_id == user_id,
                SourcePermission.revoked_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    
    if not permission:
        raise HTTPException(status_code=404, detail="Permission not found")
    
    # Soft delete (revoke)
    permission.revoked_at = datetime.utcnow()
    
    # Log the action
    audit_entry = PermissionAuditLog(
        action="revoke",
        source_id=source_id,
        user_id=user_id,
        performed_by=current_user.user_id
    )
    session.add(audit_entry)
    
    session.commit()
    
    return {"status": "success", "message": f"Revoked access for user {user_id}"}

@router.patch("/sources/{source_id}/public")
async def toggle_source_public(
    source_id: int,
    is_public: bool,
    current_user: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db)
):
    """Make a source public or private."""
    source = session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    
    source.is_public = is_public
    
    # Log the action
    audit_entry = PermissionAuditLog(
        action="modify",
        source_id=source_id,
        performed_by=current_user.user_id,
        details={"is_public": is_public}
    )
    session.add(audit_entry)
    
    session.commit()
    
    return {"status": "success", "message": f"Source is now {'public' if is_public else 'private'}"}

@router.get("/permissions/audit")
async def get_permission_audit_log(
    user_id: Optional[str] = None,
    source_id: Optional[int] = None,
    limit: int = 100,
    current_user: User = Depends(require_role(Role.ADMIN)),
    session: Session = Depends(get_db)
):
    """Get audit log of permission changes."""
    query = select(PermissionAuditLog)
    
    if user_id:
        query = query.where(PermissionAuditLog.user_id == user_id)
    if source_id:
        query = query.where(PermissionAuditLog.source_id == source_id)
    
    query = query.order_by(PermissionAuditLog.timestamp.desc()).limit(limit)
    
    result = session.execute(query)
    return result.scalars().all()
```

---

## Frontend Implementation (React)

### 1. Auth Context

```typescript
// web/src/contexts/AuthContext.tsx
import React, { createContext, useContext, useState, useEffect } from 'react';

interface User {
  userId: string;
  email: string;
  displayName: string;
  role: 'admin' | 'editor' | 'viewer';
  accessibleSources: number[];
  isAdmin: boolean;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: () => void;
  logout: () => void;
  checkSourceAccess: (sourceId: number) => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check for existing session
    const fetchUser = async () => {
      try {
        const response = await fetch('/api/auth/me', {
          credentials: 'include'
        });
        if (response.ok) {
          const userData = await response.json();
          
          // Fetch accessible sources
          const sourcesResponse = await fetch('/api/articles/sources/accessible', {
            credentials: 'include'
          });
          const sources = await sourcesResponse.json();
          
          setUser({
            ...userData,
            accessibleSources: sources.map((s: any) => s.source_id),
            isAdmin: userData.role === 'admin'
          });
        }
      } catch (error) {
        console.error('Failed to fetch user:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchUser();
  }, []);

  const login = () => {
    // Redirect to OAuth provider
    window.location.href = '/api/auth/login';
  };

  const logout = async () => {
    await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
    setUser(null);
  };

  const checkSourceAccess = (sourceId: number): boolean => {
    if (!user) return false;
    return user.isAdmin || user.accessibleSources.includes(sourceId);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, checkSourceAccess }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};
```

### 2. Protected Routes

```typescript
// web/src/components/ProtectedRoute.tsx
import { Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
}

export const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ 
  children, 
  requireAdmin = false 
}) => {
  const { user, loading } = useAuth();

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return <Navigate to="/login" />;
  }

  if (requireAdmin && !user.isAdmin) {
    return <Navigate to="/unauthorized" />;
  }

  return <>{children}</>;
};
```

### 3. Admin Panel - Permission Management

```typescript
// web/src/components/admin/PermissionManager.tsx
import React, { useState, useEffect } from 'react';
import { useAuth } from '../../contexts/AuthContext';

interface Permission {
  permissionId: number;
  sourceId: number;
  sourceName: string;
  userId: string;
  userEmail: string;
  accessLevel: 'read' | 'write' | 'admin';
  grantedAt: string;
}

export const PermissionManager: React.FC = () => {
  const { user } = useAuth();
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [users, setUsers] = useState([]);
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (user?.isAdmin) {
      fetchPermissions();
      fetchUsers();
      fetchSources();
    }
  }, [user]);

  const fetchPermissions = async () => {
    const response = await fetch('/api/admin/permissions', {
      credentials: 'include'
    });
    const data = await response.json();
    setPermissions(data);
  };

  const grantAccess = async (userId: string, sourceId: number, accessLevel: string) => {
    setLoading(true);
    try {
      await fetch('/api/admin/permissions/grant', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ user_id: userId, source_id: sourceId, access_level: accessLevel })
      });
      await fetchPermissions(); // Refresh
    } catch (error) {
      console.error('Failed to grant access:', error);
    } finally {
      setLoading(false);
    }
  };

  const revokeAccess = async (userId: string, sourceId: number) => {
    if (!confirm('Are you sure you want to revoke this access?')) return;
    
    setLoading(true);
    try {
      await fetch('/api/admin/permissions/revoke', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ user_id: userId, source_id: sourceId })
      });
      await fetchPermissions(); // Refresh
    } catch (error) {
      console.error('Failed to revoke access:', error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="permission-manager">
      <h2>Source Permission Management</h2>
      
      {/* Grant new permission form */}
      <div className="grant-form">
        <h3>Grant Access</h3>
        <select id="user-select">
          {users.map((u: any) => (
            <option key={u.user_id} value={u.user_id}>{u.email}</option>
          ))}
        </select>
        <select id="source-select">
          {sources.map((s: any) => (
            <option key={s.source_id} value={s.source_id}>{s.name}</option>
          ))}
        </select>
        <select id="access-level">
          <option value="read">Read</option>
          <option value="write">Write</option>
          <option value="admin">Admin</option>
        </select>
        <button 
          onClick={() => {
            const userId = (document.getElementById('user-select') as HTMLSelectElement).value;
            const sourceId = parseInt((document.getElementById('source-select') as HTMLSelectElement).value);
            const accessLevel = (document.getElementById('access-level') as HTMLSelectElement).value;
            grantAccess(userId, sourceId, accessLevel);
          }}
          disabled={loading}
        >
          Grant Access
        </button>
      </div>

      {/* Existing permissions table */}
      <div className="permissions-table">
        <h3>Active Permissions</h3>
        <table>
          <thead>
            <tr>
              <th>User</th>
              <th>Source</th>
              <th>Access Level</th>
              <th>Granted</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {permissions.map((p) => (
              <tr key={p.permissionId}>
                <td>{p.userEmail}</td>
                <td>{p.sourceName}</td>
                <td>{p.accessLevel}</td>
                <td>{new Date(p.grantedAt).toLocaleDateString()}</td>
                <td>
                  <button 
                    onClick={() => revokeAccess(p.userId, p.sourceId)}
                    disabled={loading}
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
```

### 4. Data Filtering in UI

```typescript
// web/src/components/ArticleList.tsx
import React, { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';

export const ArticleList: React.FC = () => {
  const { user, checkSourceAccess } = useAuth();
  const [articles, setArticles] = useState([]);
  const [selectedCounty, setSelectedCounty] = useState<string>('');
  const [selectedSource, setSelectedSource] = useState<number | null>(null);

  useEffect(() => {
    fetchArticles();
  }, [selectedCounty, selectedSource]);

  const fetchArticles = async () => {
    const params = new URLSearchParams();
    if (selectedCounty) params.append('county', selectedCounty);
    if (selectedSource) params.append('source_id', selectedSource.toString());

    const response = await fetch(`/api/articles?${params}`, {
      credentials: 'include'
    });
    
    if (response.ok) {
      const data = await response.json();
      setArticles(data);
    } else if (response.status === 403) {
      alert("You don't have access to this source");
    }
  };

  return (
    <div className="article-list">
      <div className="filters">
        <select 
          value={selectedCounty} 
          onChange={(e) => setSelectedCounty(e.target.value)}
        >
          <option value="">All Counties</option>
          <option value="Boone">Boone</option>
          <option value="Osage">Osage</option>
          <option value="Audrain">Audrain</option>
        </select>

        {/* Only show sources user has access to */}
        <select 
          value={selectedSource ?? ''} 
          onChange={(e) => setSelectedSource(e.target.value ? parseInt(e.target.value) : null)}
        >
          <option value="">All Sources</option>
          {user?.accessibleSources.map(sourceId => (
            <option key={sourceId} value={sourceId}>Source {sourceId}</option>
          ))}
        </select>
      </div>

      <div className="articles">
        {articles.map((article: any) => (
          <ArticleCard 
            key={article.article_id} 
            article={article}
            canEdit={user?.isAdmin || checkSourceAccess(article.source_id)}
          />
        ))}
      </div>
    </div>
  );
};
```

---

## Migration Guide

### Step 1: Add Schema to Existing Database

```bash
# Run migration
psql $DATABASE_URL < migrations/add_multi_tenancy.sql
```

### Step 2: Backfill Existing Data

```python
# scripts/backfill_source_ownership.py
"""
Assign existing sources to an admin user.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

def backfill_source_ownership(admin_user_id: str):
    engine = create_engine(os.environ['DATABASE_URL'])
    
    with Session(engine) as session:
        # Get all sources without owner
        sources = session.execute(
            "SELECT source_id FROM sources WHERE owner_id IS NULL"
        ).fetchall()
        
        for (source_id,) in sources:
            session.execute(
                "UPDATE sources SET owner_id = :user_id, created_by = :user_id WHERE source_id = :source_id",
                {"user_id": admin_user_id, "source_id": source_id}
            )
        
        session.commit()
        print(f"Backfilled {len(sources)} sources to admin user {admin_user_id}")

if __name__ == "__main__":
    admin_id = input("Enter admin user ID (from OAuth): ")
    backfill_source_ownership(admin_id)
```

### Step 3: Deploy Backend Changes

```bash
# Build new Docker image
docker build -t mizzou-api:v2.0 -f Dockerfile.api .

# Deploy to Kubernetes
helm upgrade mizzou-crawler ./helm \
  --set image.tag=v2.0 \
  --set multiTenancy.enabled=true
```

### Step 4: Deploy Frontend Changes

```bash
cd web
npm run build
gsutil -m rsync -r build gs://mizzou-frontend-prod
```

---

## Testing Checklist

### Unit Tests

- [ ] `test_get_accessible_source_ids()` - for each role
- [ ] `test_check_source_access()` - owner, permission, public, denied
- [ ] `test_filter_query_by_sources()` - query filtering works
- [ ] `test_grant_permission()` - admin can grant
- [ ] `test_revoke_permission()` - admin can revoke
- [ ] `test_non_admin_cannot_grant()` - authorization check

### Integration Tests

- [ ] User can only see their own sources
- [ ] User can see sources with permissions
- [ ] User can see public sources
- [ ] Admin can see all sources
- [ ] Permission grants are logged
- [ ] Permission revokes are logged
- [ ] Revoking access removes article visibility

### UI Tests

- [ ] Login flow works
- [ ] Non-admin cannot access admin panel
- [ ] Article list only shows accessible articles
- [ ] Source dropdown only shows accessible sources
- [ ] Admin can grant/revoke permissions
- [ ] Permission changes reflected immediately

---

## Performance Considerations

### Caching

```python
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=1000)
def get_accessible_source_ids_cached(user_id: str, cache_key: int) -> Set[int]:
    """
    Cached version of get_accessible_source_ids.
    cache_key changes every 5 minutes to invalidate cache.
    """
    return get_accessible_source_ids(user_id)

def get_cache_key() -> int:
    """Generate cache key that changes every 5 minutes."""
    return int(datetime.now().timestamp() // 300)

# Usage in endpoint
accessible_sources = get_accessible_source_ids_cached(
    current_user.user_id,
    get_cache_key()
)
```

### Database Indexes

All necessary indexes are included in the schema above. Key indexes:

- `idx_source_permissions_user` - Fast lookup of user's permissions
- `idx_source_permissions_source` - Fast lookup of source's permissions
- `idx_sources_owner` - Fast lookup of owned sources
- `idx_sources_public` - Fast lookup of public sources
- `idx_articles_source` - Fast filtering of articles by source

### Query Optimization

```sql
-- Use EXISTS instead of IN for large datasets
SELECT a.*
FROM articles a
WHERE EXISTS (
    SELECT 1 FROM sources s
    WHERE s.source_id = a.source_id
    AND (
        s.owner_id = 'user123'
        OR s.is_public = TRUE
        OR EXISTS (
            SELECT 1 FROM source_permissions sp
            WHERE sp.source_id = s.source_id
            AND sp.user_id = 'user123'
            AND sp.revoked_at IS NULL
        )
    )
);
```

---

## Security Best Practices

1. **Always filter at the API layer** - Never trust client-side filtering
2. **Use parameterized queries** - Prevent SQL injection
3. **Log all permission changes** - Audit trail for compliance
4. **Rate limit permission APIs** - Prevent abuse
5. **Validate access on every request** - Don't rely on cached permissions for writes
6. **Use HTTPS only** - Protect OAuth tokens in transit
7. **Implement CSRF protection** - For state-changing operations
8. **Regular security audits** - Review permission grants monthly

---

## Monitoring & Alerts

### Key Metrics

```python
# Track permission-related metrics
from google.cloud import monitoring_v3

def record_permission_check(user_id: str, source_id: int, granted: bool):
    """Record permission check for monitoring."""
    record_metric(
        "permission_checks",
        1,
        labels={
            "user_id": user_id,
            "source_id": str(source_id),
            "granted": str(granted)
        }
    )

def record_permission_change(action: str, performed_by: str):
    """Record permission grant/revoke."""
    record_metric(
        "permission_changes",
        1,
        labels={
            "action": action,
            "performed_by": performed_by
        }
    )
```

### Alert Rules

- **High permission denial rate**: > 10% of requests denied (possible misconfiguration)
- **Unusual permission grants**: > 10 grants in 1 hour (possible abuse)
- **Failed admin access attempts**: Non-admin trying to access admin endpoints
- **Slow permission queries**: > 500ms query time (needs optimization)

---

## Support & Troubleshooting

### Common Issues

**Q: User can't see their sources after creation**
A: Check that `owner_id` is set correctly on source creation

**Q: Admin can't see all sources**
A: Verify user role is set to 'admin' in database

**Q: Permission grants not taking effect**
A: Clear cache or wait 5 minutes for cache expiration

**Q: Performance degradation with many sources**
A: Review query plans, ensure indexes are used

### Debug Queries

```sql
-- Check user's accessible sources
SELECT s.source_id, s.name, s.owner_id, s.is_public
FROM sources s
WHERE s.owner_id = 'user123'
   OR s.is_public = TRUE
   OR EXISTS (
       SELECT 1 FROM source_permissions sp
       WHERE sp.source_id = s.source_id
       AND sp.user_id = 'user123'
       AND sp.revoked_at IS NULL
   );

-- Check permission audit log
SELECT *
FROM permission_audit_log
WHERE user_id = 'user123'
ORDER BY timestamp DESC
LIMIT 20;
```

---

*This implementation provides secure, performant, source-based multi-tenancy without the complexity of separate tenant infrastructure.*
