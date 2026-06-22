import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import './index.css'
import App from './App'
import Home from './views/Home'
import ProjectHub from './views/ProjectHub'
import Sanctum from './views/Sanctum'
import TomeReader from './views/TomeReader'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Home /> },
      { path: 'project/:name', element: <ProjectHub /> },
      { path: 'sanctum', element: <Sanctum /> },
      { path: 'tome/:id', element: <TomeReader /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
