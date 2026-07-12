import { useCallback, useEffect, useRef, useState } from 'react'

import { User, apiJson } from '../lib/api'
import { canDeleteUser } from '../lib/userDelete'

type UserListProps = {
  active: boolean
  onUsersChanged?: () => void
}

export function UserList({ active, onUsersChanged }: UserListProps) {
  const [users, setUsers] = useState<User[]>([])
  const [editing, setEditing] = useState<User | null>(null)
  const [editNim, setEditNim] = useState('')
  const [editName, setEditName] = useState('')
  const [deleteUser, setDeleteUser] = useState<User | null>(null)
  const [deleteText, setDeleteText] = useState('')
  const [deleting, setDeleting] = useState(false)
  const deleteBusyRef = useRef(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const loadUsers = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setUsers(await apiJson<User[]>('/api/users'))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadUsers()
  }, [loadUsers])

  const startEdit = (user: User) => {
    setEditing(user)
    setEditNim(user.nim)
    setEditName(user.name)
    setError('')
  }

  const saveEdit = async () => {
    if (!editing) return
    try {
      await apiJson<User>(`/api/users/${editing.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ nim: editNim, name: editName }),
      })
      setEditing(null)
      await loadUsers()
      onUsersChanged?.()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update user')
      await loadUsers()
    }
  }

  const removeUser = async () => {
    if (deleteBusyRef.current || !deleteUser || !canDeleteUser(deleteText, deleteUser.nim)) return
    deleteBusyRef.current = true
    setDeleting(true)
    try {
      await apiJson<{ success: boolean }>(`/api/users/${deleteUser.id}`, { method: 'DELETE' })
      setDeleteUser(null)
      setDeleteText('')
      await loadUsers()
      onUsersChanged?.()
    } catch (err) {
      await loadUsers()
      setError(err instanceof Error ? err.message : 'Failed to delete user')
    } finally {
      deleteBusyRef.current = false
      setDeleting(false)
    }
  }

  return (
    <section className={`panel${active ? ' active' : ''}`} id="panel-user">
      <div className="users-section">
        <div className="users-header"><h3 className="users-title">Enrolled users</h3></div>
        {error && <div className="users-empty">{error}</div>}
        <div className="users-table-wrap">
          <table className="users-table">
            <thead>
              <tr><th>NIM</th><th>Name</th><th>Registered</th><th>Actions</th></tr>
            </thead>
            <tbody id="usersTableBody">
              {loading ? (
                <tr className="users-empty-row"><td colSpan={4}><div className="users-empty">Loading users…</div></td></tr>
              ) : users.length === 0 ? (
                <tr className="users-empty-row"><td colSpan={4}><div className="users-empty">No users enrolled yet.</div></td></tr>
              ) : users.map((user) => (
                <tr key={user.id}>
                  <td>{user.nim}</td>
                  <td>{user.name}</td>
                  <td>{user.created_at}</td>
                  <td>
                    <div className="user-table-actions">
                      <button className="user-action-btn" type="button" onClick={() => startEdit(user)}>Edit</button>
                      <button
                        className="user-action-btn danger"
                        type="button"
                        disabled={deleting}
                        onClick={() => { setDeleteUser(user); setDeleteText('') }}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {editing && (
          <form className="inline-form" onSubmit={(event) => { event.preventDefault(); void saveEdit() }}>
            <h3>Edit user</h3>
            <input className="field-input" aria-label="NIM" value={editNim} onChange={(event) => setEditNim(event.target.value)} />
            <input className="field-input" aria-label="Full name" value={editName} onChange={(event) => setEditName(event.target.value)} />
            <div className="inline-actions">
              <button className="btn btn-primary" type="submit">Save</button>
              <button className="btn btn-ghost" type="button" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </form>
        )}

        {deleteUser && (
          <div className="inline-form danger-zone" aria-busy={deleting}>
            <h3>Delete {deleteUser.name}?</h3>
            <p>Historical logs stay, but they lose the user link. Type <strong>{deleteUser.nim}</strong> to confirm.</p>
            <input
              className="field-input"
              aria-label="Confirm NIM"
              value={deleteText}
              disabled={deleting}
              onChange={(event) => setDeleteText(event.target.value)}
            />
            <div className="inline-actions">
              <button
                type="button"
                className="btn btn-danger"
                disabled={deleting || !canDeleteUser(deleteText, deleteUser.nim)}
                onClick={() => void removeUser()}
              >
                {deleting && <span className="btn-spinner" aria-hidden="true" />}
                {deleting ? 'Deleting…' : 'Delete user'}
              </button>
              <button type="button" className="btn btn-ghost" disabled={deleting} onClick={() => setDeleteUser(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
