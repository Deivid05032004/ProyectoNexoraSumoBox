import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './LoginAdmin.css';

export default function LoginAdmin() {
  const navigate = useNavigate();
  const [usuario, setUsuario] = useState('');
  const [password, setPassword] = useState('');
  const [mensaje, setMensaje] = useState({ texto: '', exito: false });
  const [cargando, setCargando] = useState(false);

  function handleSubmit(event) {
    event.preventDefault();
    setCargando(true);
    setMensaje({ texto: '', exito: false });

    // Normalizar usuario
    const userTrim = usuario.trim();
    const passTrim = password.trim();

    // Verificación de credenciales de prueba
    if (!userTrim) {
      setMensaje({ texto: 'Por favor, ingresa tu usuario (ej. revisor1).', exito: false });
      setCargando(false);
      return;
    }

    if (!passTrim) {
      setMensaje({ texto: 'Por favor, ingresa tu contraseña.', exito: false });
      setCargando(false);
      return;
    }

    // Aceptar cualquier revisor de prueba con la contraseña 'eventix' o credenciales válidas
    const esPasswordValida = passTrim.toLowerCase() === 'eventix';

    if (!esPasswordValida) {
      setMensaje({
        texto: 'Contraseña incorrecta. Para este prototipo usa la contraseña: eventix',
        exito: false,
      });
      setCargando(false);
      return;
    }

    // Simular inicio de sesión exitoso
    setTimeout(() => {
      const revisorId = userTrim.toLowerCase();
      sessionStorage.setItem('uta.revisor', revisorId);
      sessionStorage.setItem('uta.access_token', `mock_token_${Date.now()}`);
      sessionStorage.setItem(
        'uta.user',
        JSON.stringify({
          username: revisorId,
          first_name: revisorId,
          role: 'ADMIN',
        })
      );

      // Notificar cambio de sesión en el navegador
      window.dispatchEvent(new Event('uta-session-changed'));

      // Redirigir a la nueva ruta del panel administrativo
      navigate('/admin/dashboard', { replace: true });
    }, 200);
  }

  return (
    <div className="login-admin-container">
      <div className="login-admin-card">
        <p className="admin-eyebrow">UTA SUMO ROBOTICS CUP 2026</p>
        <h1 className="login-admin-title">Acceso de Revisores</h1>
        <p className="admin-login-description">
          Ingreso exclusivo para jueces y personal técnico del torneo.
        </p>

        <form className="login-admin-form" onSubmit={handleSubmit}>
          <div className="login-form-group">
            <label htmlFor="admin-usuario" className="login-form-label">
              Usuario de revisor
            </label>
            <input
              id="admin-usuario"
              type="text"
              className="login-form-input"
              value={usuario}
              onChange={(e) => setUsuario(e.target.value)}
              placeholder="ej. revisor1"
              required
              autoComplete="username"
            />
          </div>

          <div className="login-form-group">
            <label htmlFor="admin-password" className="login-form-label">
              Contraseña
            </label>
            <input
              id="admin-password"
              type="password"
              className="login-form-input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Contraseña asignada"
              required
              autoComplete="current-password"
            />
          </div>

          {mensaje.texto && (
            <p
              className={`admin-login-message${mensaje.exito ? ' admin-login-success' : ''}`}
              role={mensaje.exito ? 'status' : 'alert'}
            >
              {mensaje.texto}
            </p>
          )}

          <button type="submit" className="login-admin-submit-btn" disabled={cargando}>
            {cargando ? 'Validando credenciales...' : 'Ingresar al panel'}
          </button>
        </form>

        <p className="login-admin-footer">
          <strong>Credenciales de prueba:</strong> usuarios <code>revisor1</code> a <code>revisor4</code>, contraseña <code>eventix</code>.
        </p>
      </div>
    </div>
  );
}
