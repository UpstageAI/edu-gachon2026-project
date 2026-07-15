import { Route, Routes } from 'react-router-dom';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { HomePage } from './pages/HomePage';
import { IngredientSelectPage } from './pages/IngredientSelectPage';
import { AllergySetupPage } from './pages/AllergySetupPage';
import { RecipeConfirmPage } from './pages/RecipeConfirmPage';
import { RecipeLoadingPage } from './pages/RecipeLoadingPage';
import { RecipeDetailPage } from './pages/RecipeDetailPage';
import { CookingStepsPage } from './pages/CookingStepsPage';
import { CookingCompletePage } from './pages/CookingCompletePage';
import { ProfileEditPage } from './pages/ProfileEditPage';

function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/home" element={<HomePage />} />
      <Route path="/ingredients" element={<IngredientSelectPage />} />
      <Route path="/allergies" element={<AllergySetupPage />} />
      <Route path="/recipes/confirm" element={<RecipeConfirmPage />} />
      <Route path="/recipes/loading" element={<RecipeLoadingPage />} />
      <Route path="/recipes/detail" element={<RecipeDetailPage />} />
      <Route path="/cooking/steps" element={<CookingStepsPage />} />
      <Route path="/cooking/complete" element={<CookingCompletePage />} />
      <Route path="/profile" element={<ProfileEditPage />} />
    </Routes>
  );
}

export default App;
