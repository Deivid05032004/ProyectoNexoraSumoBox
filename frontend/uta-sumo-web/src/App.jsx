import { useEffect, useState } from 'react'
import './App.css'

const API_URL = 'http://127.0.0.1:8000/api/v1'

function App() {
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function cargarCategorias() {
      try {
        setLoading(true)
        setError('')

        const response = await fetch(`${API_URL}/categories`, {
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error('No se pudieron consultar las categorías.')
        }

        const data = await response.json()
        setCategories(data)
      } catch (err) {
        if (err.name !== 'AbortError') {
          setError(
            'No fue posible conectar con el servidor. Comprueba que la API esté funcionando.'
          )
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    cargarCategorias()

    return () => controller.abort()
  }, [])

  return (
    <main className="app">
      <header className="topbar">
        <a className="brand" href="#inicio">
          <span className="brand-mark">UTA</span>
          <span>
            <strong>SUMO ROBOTICS CUP</strong>
            <small>Competencia de robótica</small>
          </span>
        </a>

        <a className="nav-link" href="#categorias">
          Categorías
        </a>
      </header>

      <section className="hero" id="inicio">
        <div className="hero-content">
          <span className="eyebrow">TECNOLOGÍA · INGENIO · COMPETENCIA</span>

          <h1>
            UTA SUMO
            <span>ROBOTICS CUP</span>
          </h1>

          <p>
            El desafío donde la creatividad, la programación y la ingeniería
            se encuentran en el ring.
          </p>

          <a className="primary-button" href="#categorias">
            Explorar categoría <span aria-hidden="true">→</span>
          </a>
        </div>

        <div className="robot-illustration" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="robot">
            <div className="robot-top" />
            <div className="robot-eye eye-left" />
            <div className="robot-eye eye-right" />
            <div className="robot-mouth" />
            <div className="robot-base" />
            <div className="robot-wheel wheel-left" />
            <div className="robot-wheel wheel-right" />
          </div>
          <span className="robot-label">READY TO COMPETE</span>
        </div>
      </section>

      <section className="categories-section" id="categorias">
        <div className="section-heading">
          <div>
            <span className="eyebrow">PARTICIPA EN EL TORNEO</span>
            <h2>Categorías disponibles</h2>
          </div>
          <span className="live-indicator">
            <span /> Datos del servidor
          </span>
        </div>

        {loading && (
          <p className="feedback" role="status">
            Cargando categorías...
          </p>
        )}

        {error && (
          <div className="feedback error" role="alert">
            <p>{error}</p>
            <button
              className="secondary-button"
              onClick={() => window.location.reload()}
            >
              Intentar nuevamente
            </button>
          </div>
        )}

        {!loading && !error && categories.length === 0 && (
          <p className="feedback">
            Por el momento no hay categorías disponibles.
          </p>
        )}

        {!loading && !error && categories.length > 0 && (
          <div className="category-grid">
            {categories.map((category) => (
              <article className="category-card" key={category.id}>
                <div className="card-icon" aria-hidden="true">
                  <svg
                    viewBox="0 0 48 48"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                  >
                    <rect
                      x="8"
                      y="14"
                      width="32"
                      height="24"
                      rx="6"
                      stroke="currentColor"
                      strokeWidth="2.5"
                    />
                    <path
                      d="M17 14V9H31V14M16 38V42M32 38V42M17 24H18M30 24H31M19 31H29"
                      stroke="currentColor"
                      strokeWidth="2.5"
                      strokeLinecap="round"
                    />
                  </svg>
                </div>

                <span className="category-tag">CATEGORÍA OFICIAL</span>
                <h3>{category.name}</h3>
                <p>
                  {category.description ||
                    'Descubre el desafío y prepárate para competir.'}
                </p>

                <button
                  className="text-button"
                  onClick={() =>
                    alert(
                      'El formulario de inscripción estará disponible en la siguiente etapa.'
                    )
                  }
                >
                  Próximamente: inscripciones <span>→</span>
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      <footer className="footer">
        <span>UTA SUMO ROBOTICS CUP</span>
        <span>Ingeniería que se pone a prueba.</span>
      </footer>
    </main>
  )
}

export default App
