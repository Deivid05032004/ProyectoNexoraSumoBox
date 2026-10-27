import { useEffect, useState } from 'react';
import { apiRequest } from './services/adminApi';
import './AdminCreateForm.css';

export default function AdminCreateForm({ onClose }) {
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [users, setUsers] = useState([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [userError, setUserError] = useState('');
  async function loadUsers() {
    setLoadingUsers(true); setUserError('');
    try { const rows = await apiRequest('/api/v1/admin/users?page=1&limit=100'); setUsers(rows); }
    catch (err) { setUserError(err.message); }
    finally { setLoadingUsers(false); }
  }
  useEffect(() => { const timer = window.setTimeout(() => loadUsers(), 0); return () => window.clearTimeout(timer); }, []);
  async function submit(event) {
    event.preventDefault();
    setMessage(''); setError(''); setSaving(true);
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      const result = await apiRequest('/api/v1/admin/users', { method: 'POST', body: JSON.stringify(Object.fromEntries(form)) });
      setMessage(`Cuenta ${result.email} creada con rol ${result.role}. Entrega la contraseña al usuario por un canal seguro.`);
      formElement.reset();
      await loadUsers();
    } catch (err) { setError(err.message || 'No se pudo crear la cuenta.'); }
    finally { setSaving(false); }
  }
  return <div className="admin-create-overlay" role="dialog" aria-modal="true" aria-labelledby="admin-create-title">
    <form className="admin-create-card" onSubmit={submit}>
      <button type="button" className="admin-create-close" onClick={onClose} aria-label="Cerrar">×</button>
      <p className="admin-eyebrow">GESTIÓN DE ACCESOS</p>
      <h2 id="admin-create-title">Nuevo administrador</h2>
      <p>Completa los datos para preparar una nueva cuenta administrativa.</p>
      <label>Nombre<input required name="first_name" autoComplete="given-name" /></label>
      <label>Apellido<input required name="last_name" autoComplete="family-name" /></label>
      <label>Correo electrónico<input required type="email" name="email" autoComplete="email" /></label>
      <label>Rol<select name="role" defaultValue="ADMIN"><option value="ADMIN">Administrador</option><option value="EVENT_MANAGER">Gestor de evento</option></select></label>
      <label>Contraseña temporal<input required name="password" type="password" minLength="15" maxLength="128" autoComplete="new-password" /><small>15 caracteres mínimo. Entrégala por un canal seguro.</small></label>
      {error && <div className="admin-create-notice" role="alert">{error}</div>}
      {message && <div className="admin-create-notice" role="status">{message}</div>}
      <div className="admin-user-list"><h3>Usuarios y roles</h3>{userError&&<p role="alert">{userError}</p>}{loadingUsers?<p>Cargando usuarios…</p>:users.map(user=><div className="admin-user-row" key={user.id}><span><strong>{user.first_name} {user.last_name}</strong><small>{user.email}</small></span><select aria-label={`Rol de ${user.email}`} value={user.role} onChange={async e=>{try{await apiRequest(`/api/v1/admin/users/${user.id}`,{method:'PATCH',body:JSON.stringify({role:e.target.value})});await loadUsers();}catch(err){setUserError(err.message);}}}><option value="ADMIN">ADMIN</option><option value="EVENT_MANAGER">EVENT_MANAGER</option><option value="PARTICIPANT">PARTICIPANT</option></select><button type="button" onClick={async()=>{try{await apiRequest(`/api/v1/admin/users/${user.id}`,{method:'PATCH',body:JSON.stringify({is_active:!user.is_active})});await loadUsers();}catch(err){setUserError(err.message);}}}>{user.is_active?'Desactivar':'Activar'}</button></div>)}</div>
      <div className="admin-create-actions"><button type="button" onClick={onClose}>Cerrar</button><button type="submit" disabled={saving}>{saving ? 'Creando…' : 'Registrar cuenta'}</button></div>
    </form>
  </div>;
}
