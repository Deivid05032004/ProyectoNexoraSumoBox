import { useState } from 'react';
import './LoginAdmin.css';

export default function LoginAdmin() {
  const [usuario, setUsuario] = useState('');
  const [contrasena, setContrasena] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    console.log('Credenciales ingresadas:', {
      usuario,
      contrasena,
    });
  };

  return (
    <div className="login-admin-container">
      <div className="login-admin-card">
        <h1 className="login-admin-title">Ingreso de revisores</h1>

        <form className="login-admin-form" onSubmit={handleSubmit}>
          <div className="login-form-group">
            <label htmlFor="usuario" className="login-form-label">
              Usuario
            </label>
            <input
              id="usuario"
              type="text"
              className="login-form-input"
              value={usuario}
              onChange={(e) => setUsuario(e.target.value)}
              placeholder="Ingrese su usuario"
              required
              autoComplete="username"
            />
          </div>

          <div className="login-form-group">
            <label htmlFor="contrasena" className="login-form-label">
              Contraseña
            </label>
            <input
              id="contrasena"
              type="password"
              className="login-form-input"
              value={contrasena}
              onChange={(e) => setContrasena(e.target.value)}
              placeholder="Ingrese su contraseña"
              required
              autoComplete="current-password"
            />
          </div>

          <button type="submit" className="login-admin-submit-btn">
            Ingresar
          </button>
        </form>

        <p className="login-admin-footer">
          Prototipo: usuarios revisor1 a revisor4, contraseña eventix.
        </p>
      </div>
    </div>
  );
}

