import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiRequest, clearAdminSession } from './services/adminApi';
import NavIcon from '../components/NavIcon';

export default function AdminPasswordSettings({ required = false }) {
  const navigate = useNavigate();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [changed, setChanged] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setError('');
    setMessage('');
    if (newPassword.length < 15) {
      setError('La nueva contraseña debe tener al menos 15 caracteres.');
      return;
    }
    if (newPassword !== confirmation) {
      setError('La confirmación no coincide con la nueva contraseña.');
      return;
    }
    setSaving(true);
    try {
      await apiRequest('/api/v1/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      sessionStorage.setItem('uta.password_changed_message', 'Contraseña actualizada. Inicia sesión con tu nueva contraseña.');
      clearAdminSession();
      setChanged(true);
      setMessage('Contraseña actualizada. Por seguridad, inicia sesión nuevamente con tu nueva contraseña.');
    } catch (requestError) {
      setError(requestError.message || 'No se pudo actualizar la contraseña.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="admin-security-card" aria-labelledby="admin-security-title">
      <div className="admin-security-intro">
        <span className="admin-security-icon"><NavIcon name="security" size={24} /></span>
        <div>
          <span className="admin-event-kicker">SEGURIDAD DE LA CUENTA</span>
          <h2 id="admin-security-title">Actualizar contraseña</h2>
          <p>{required
            ? 'Antes de administrar el evento, reemplaza la contraseña inicial por una personal y segura.'
            : 'Actualiza periódicamente la contraseña de tu cuenta administrativa.'}</p>
        </div>
      </div>
      {required && !changed && <div className="admin-security-notice" role="status">
        Esta cuenta conserva la contraseña inicial. Debes cambiarla para acceder a las demás funciones del panel.
      </div>}
      {!changed ? <form className="admin-security-form" onSubmit={submit}>
        <label>Contraseña actual<input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" required maxLength={128} /></label>
        <label>Nueva contraseña<input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" required minLength={15} maxLength={128} aria-describedby="admin-password-hint" /></label>
        <label>Confirmar nueva contraseña<input type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} autoComplete="new-password" required minLength={15} maxLength={128} /></label>
        <p id="admin-password-hint" className="admin-security-hint">Mínimo 15 caracteres. El sistema también rechazará contraseñas comunes o predecibles.</p>
        {error && <div className="admin-security-message is-error" role="alert">{error}</div>}
        <button className="admin-security-submit" type="submit" disabled={saving}>{saving ? 'Actualizando…' : 'Guardar nueva contraseña'}</button>
      </form> : <div className="admin-security-message is-success" role="status">{message}
        <button type="button" className="admin-security-submit" onClick={() => navigate('/admin', { replace: true })}>Ir al inicio de sesión</button>
      </div>}
    </section>
  );
}
